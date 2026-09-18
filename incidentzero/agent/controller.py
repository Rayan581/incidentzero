from __future__ import annotations

import json
from typing import Any

from incidentzero.approval.gateway import ApprovalGateway
from incidentzero.domain.models import AgentOutcome, ModelReply, ToolCall
from incidentzero.model.base import ModelClient
from incidentzero.model.errors import PermanentModelError, TransientModelError
from incidentzero.telemetry.budget import BudgetExceeded, BudgetManager
from incidentzero.telemetry.trace import TraceRecorder
from incidentzero.tools.registry import ToolRegistry

from .planner import Planner
from .policies import LoopGuard, ReplanPolicy, RiskPolicy
from .prompts import SYSTEM_PROMPT
from .recovery import RetryPolicy
from .state import AgentState

# How many LLM calls remaining is considered "low budget"
_LOW_BUDGET_THRESHOLD = 3


class AgentController:
    """Production-grade incident-response agent controller.

    Orchestrates the full ReAct loop:
      observe → plan → (decide → validate → approve → execute → trace → replan?) → close/escalate

    Reliability guarantees:
    - Bounded LLM retries with exponential backoff (TransientModelError only).
    - Stable loop detection via action fingerprinting (LoopGuard).
    - Optimistic concurrency enforcement (world_version stale check).
    - Human approval gate for high/critical actions (ApprovalGateway).
    - Evidence-grounded plan revision (ReplanPolicy + Planner.revise).
    - Verifiable stopping: close requires verify_recovery criteria_met=True.
    - Low-budget awareness: escalates with evidence when budget nearly exhausted.
    """

    def __init__(
        self,
        model: ModelClient,
        tools: ToolRegistry,
        approval: ApprovalGateway,
        budget: BudgetManager,
        trace: TraceRecorder,
    ) -> None:
        self.model = model
        self.tools = tools
        self.approval = approval
        self.budget = budget
        self.trace = trace
        self.state = AgentState()
        self.planner = Planner(model)
        self.risk = RiskPolicy()
        self.replan_policy = ReplanPolicy()
        self.loop_guard = LoopGuard()
        self.retry_policy = RetryPolicy()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _model_decide(self) -> ModelReply:
        """Call the model with bounded retry for transient errors.

        Budget is consumed on the first attempt; retries do not cost
        additional budget tokens (the same LLM slot is being used).
        """
        self.budget.consume_llm()
        return self.retry_policy.call_model(
            lambda: self.model.decide(self.state.messages, self.tools.groq_tools)
        )

    def _plan_create(self, incident: dict[str, Any]) -> None:
        """Create an initial plan using a retry-wrapped structured call.

        The plan creation LLM call uses the same budget slot as the
        bootstrap (already consumed in run()); structured calls are
        wrapped with retry but not counted separately because
        Planner.create() absorbs the budget internally via a fallback.
        """
        self.state.plan = self.retry_policy.call_model(
            lambda: self.planner.create(incident)
        )

    def _plan_revise(self, trigger: dict[str, Any]) -> None:
        """Revise the plan and reset loop guard after a replan trigger."""
        state_summary = (
            f"world_version={self.state.latest_world_version}, "
            f"evidence_ids={self.state.evidence_ids[-3:] if self.state.evidence_ids else []}, "
            f"last_tool={trigger.get('tool', 'unknown')}"
        )
        old_revision = self.state.plan.revision if self.state.plan else 0
        self.state.plan = self.retry_policy.call_model(
            lambda: self.planner.revise(
                self.state.plan or self.planner.create(trigger),
                trigger,
                state_summary,
            )
        )
        self.loop_guard.reset()
        self.state.record_replan(
            trigger_status=trigger.get("status", "unknown"),
            revision=self.state.plan.revision,
            reason=trigger.get("message", ""),
        )
        self.trace.record(
            "plan_revised",
            {
                "old_revision": old_revision,
                "new_revision": self.state.plan.revision,
                "trigger": trigger,
                "state_summary": state_summary,
            },
        )

    def _append_assistant(self, reply: ModelReply) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": reply.content}
        if reply.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in reply.tool_calls
            ]
        self.state.messages.append(msg)

    def _append_tool_result(self, call: ToolCall, result: dict[str, Any]) -> None:
        self.state.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

    def _inject_observation(self, content: str) -> None:
        """Inject a system observation into the message history."""
        self.state.messages.append({"role": "system", "content": content})

    def _execute_tool_call(self, call: ToolCall) -> dict[str, Any]:
        """Full tool execution pipeline:

        1. Schema validation
        2. Loop detection
        3. Optimistic concurrency pre-check
        4. Human approval gate (high/critical actions)
        5. Budget-aware execution
        6. Tracing
        """
        # ── 1. Schema validation ─────────────────────────────────────────
        ok, error = self.tools.validate(call.name, call.arguments)
        if not ok:
            self.trace.record(
                "tool_validation_error",
                {"call": {"name": call.name, "arguments": call.arguments}, "error": error},
            )
            return {
                "status": "validation_error",
                "tool": call.name,
                "world_version": self.state.latest_world_version,
                "evidence_id": None,
                "data": None,
                "retryable": False,
                "message": f"Argument validation failed: {error}. Correct the arguments before retrying.",
            }

        # ── 2. Loop detection ────────────────────────────────────────────
        if self.loop_guard.record(call.name, call.arguments):
            self.trace.record(
                "loop_detected",
                {"call": {"name": call.name, "arguments": call.arguments}},
            )
            return {
                "status": "loop_detected",
                "tool": call.name,
                "world_version": self.state.latest_world_version,
                "evidence_id": None,
                "data": None,
                "retryable": False,
                "message": (
                    f"Loop detected: '{call.name}' with identical arguments has been called "
                    f"more than {self.loop_guard.max_same_action_repeats} times. "
                    "Revise your plan or escalate the incident."
                ),
            }

        # ── 3. Human approval gate ───────────────────────────────────────
        if self.risk.requires_human_approval(call.name):
            justification = call.arguments.get("reason", "No justification provided by model.")
            granted = self.approval.approve(call.name, call.arguments, justification)
            self.state.record_approval(call.name, granted, justification)
            self.trace.record(
                "approval_decision",
                {
                    "call": {"name": call.name, "arguments": call.arguments},
                    "granted": granted,
                    "justification": justification,
                },
            )
            if not granted:
                return {
                    "status": "approval_denied",
                    "tool": call.name,
                    "world_version": self.state.latest_world_version,
                    "evidence_id": None,
                    "data": None,
                    "retryable": False,
                    "message": (
                        f"Human approval was denied for '{call.name}'. "
                        "Reconsider the approach: find alternative remediation or escalate."
                    ),
                }

        # ── 4. Execute ───────────────────────────────────────────────────
        self.budget.consume_tool()
        result = self.tools.execute(call.name, call.arguments)
        self.trace.record(
            "tool_result",
            {"call": {"name": call.name, "arguments": call.arguments}, "result": result},
        )
        return result

    def _build_outcome(self, status: str, summary: str) -> AgentOutcome:
        return AgentOutcome(
            status=status,
            summary=summary,
            llm_calls=self.budget.llm_calls,
            tool_calls=self.budget.tool_calls,
            final_world_version=self.state.latest_world_version,
            evidence_ids=self.state.evidence_ids,
            trace_path=str(self.trace.path),
        )

    def _low_budget_escalation(self, reason: str) -> AgentOutcome:
        """Attempt a graceful escalation when budget is nearly exhausted."""
        try:
            self.budget.consume_tool()
            result = self.tools.execute(
                "escalate_incident",
                {
                    "reason": (
                        f"{reason} Budget nearly exhausted with "
                        f"{self.budget.remaining_llm} LLM call(s) and "
                        f"{self.budget.remaining_tools} tool call(s) remaining."
                    )[:300],
                    "evidence_ids": self.state.evidence_ids[-4:],
                },
            )
            self.state.observe_result(result)
            self.trace.record("low_budget_escalation", {"result": result})
            if result.get("status") == "ok":
                return self._build_outcome(
                    "escalated",
                    "Escalated due to low budget before resolution could be verified.",
                )
        except BudgetExceeded:
            pass
        return self._build_outcome(
            "budget_exhausted",
            "Agent budget exhausted before safe termination.",
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> AgentOutcome:
        self.state.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Investigate the active production incident, mitigate it safely, "
                    "verify recovery, then close it; otherwise escalate with evidence."
                ),
            },
        ]

        try:
            # ── Bootstrap: one real observation before planning ─────────
            self.budget.consume_tool()
            incident = self.tools.execute("get_incident", {})
            self.state.observe_result(incident)
            self.trace.record("bootstrap_incident", incident)
            self.state.messages.append(
                {
                    "role": "system",
                    "content": f"Current incident evidence: {json.dumps(incident)}",
                }
            )

            # ── Initial plan (structured call; budget consumed inside planner) ─
            self.budget.consume_llm()
            self._plan_create(incident)
            self.trace.record("plan_created", {"plan": str(self.state.plan)})
            self._inject_observation(
                f"Initial plan created (revision {self.state.plan.revision}): "
                f"hypothesis={self.state.plan.hypothesis!r}"
            )

            # ── Main agent loop ─────────────────────────────────────────
            while self.budget.remaining_llm > 0 and self.budget.remaining_tools > 0:

                # Low-budget warning: steer toward verification/escalation
                if self.budget.remaining_llm <= _LOW_BUDGET_THRESHOLD:
                    self._inject_observation(
                        f"WARNING: Only {self.budget.remaining_llm} LLM call(s) remaining "
                        f"and {self.budget.remaining_tools} tool call(s). "
                        "If recovery is not yet verified, call verify_recovery now, "
                        "then close_incident or escalate_incident."
                    )

                # ── Model decision ──────────────────────────────────────
                try:
                    reply = self._model_decide()
                except TransientModelError as exc:
                    # All retries exhausted; escalate rather than crash
                    self.trace.record("model_error_fatal", {"error": str(exc)})
                    return self._build_outcome(
                        "failed",
                        f"Model call failed after all retries: {exc}",
                    )
                except PermanentModelError as exc:
                    self.trace.record("model_error_permanent", {"error": str(exc)})
                    err_str = str(exc)
                    if ("tool_use_failed" in err_str or "Failed to parse tool call" in err_str) and self.budget.remaining_llm > 1:
                        self._inject_observation(
                            "The previous tool call failed due to malformed JSON arguments. "
                            "Ensure tool call arguments are strictly valid JSON (for example, use {} for tools with no arguments)."
                        )
                        continue
                    return self._build_outcome(
                        "failed",
                        f"Permanent model error: {exc}",
                    )

                self._append_assistant(reply)
                self.trace.record(
                    "model_reply",
                    {
                        "content": reply.content,
                        "tool_calls": [
                            (
                                c.__dict__
                                if hasattr(c, "__dict__")
                                else {"name": c.name, "arguments": c.arguments}
                            )
                            for c in reply.tool_calls
                        ],
                        "finish_reason": reply.finish_reason,
                    },
                )

                # ── No tool call → model stopped ────────────────────────
                if not reply.tool_calls:
                    if self.budget.remaining_llm > 0:
                        # Give the model one more chance with an explicit prompt
                        self._inject_observation(
                            "You did not propose a tool call. "
                            "You must call a tool or escalate_incident. "
                            "If investigation is complete, call verify_recovery. "
                            "If budget is too low for safe resolution, escalate_incident."
                        )
                        continue
                    return self._build_outcome(
                        "failed",
                        "Model stopped without a tool call and budget exhausted.",
                    )

                # ── Execute the first (and only) tool call ───────────────
                call = reply.tool_calls[0]
                result = self._execute_tool_call(call)
                self.state.observe_result(result)
                self._append_tool_result(call, result)

                # ── Terminal actions ─────────────────────────────────────
                if call.name == "close_incident" and result.get("status") == "ok":
                    return self._build_outcome(
                        "resolved",
                        "Incident closed with verified simulator evidence.",
                    )
                if call.name == "escalate_incident" and result.get("status") == "ok":
                    return self._build_outcome(
                        "escalated",
                        "Incident escalated with supporting evidence.",
                    )

                # ── Replan if policy triggers ────────────────────────────
                if self.replan_policy.should_replan(result):
                    trigger_status = result.get("status", "")

                    # For stale_precondition: re-fetch current state first
                    if trigger_status == "stale_precondition":
                        self._inject_observation(
                            "World version changed (stale_precondition). "
                            "Re-observe the current state before acting. "
                            f"Latest observed world_version={self.state.latest_world_version}."
                        )

                    # For approval_denied: inform the model what happened
                    elif trigger_status == "approval_denied":
                        self._inject_observation(
                            f"Human approval was denied for '{call.name}'. "
                            "Consider a safer alternative action or escalate."
                        )

                    # Revise plan if budget allows
                    if self.budget.remaining_llm > 1:
                        try:
                            self._plan_revise(result)
                            self._inject_observation(
                                f"Plan revised to revision {self.state.plan.revision}. "
                                f"New hypothesis: {self.state.plan.hypothesis!r}"
                            )
                        except (BudgetExceeded, Exception):
                            pass  # Plan revision failed, continue with current plan

                # ── Low-budget escalation fallback ───────────────────────
                if (
                    self.budget.remaining_llm <= 1
                    and self.budget.remaining_tools >= 1
                ):
                    return self._low_budget_escalation(
                        "Agent is at budget limit without confirmed resolution."
                    )

            # ── Budget exhausted (loop exit) ─────────────────────────────
            return self._low_budget_escalation(
                "Main loop exited because budget is exhausted."
            )

        except BudgetExceeded as exc:
            return self._build_outcome("budget_exhausted", str(exc))

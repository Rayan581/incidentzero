from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from incidentzero.domain.models import AgentPlan


@dataclass
class AgentState:
    """Full observable state of the agent runtime.

    Tracks conversation history, plan, evidence, world version,
    recent tool results, approval outcomes, and replan history.
    All fields are used by AgentController to make decisions without
    depending on natural-language content of messages.
    """

    # Conversation history (OpenAI-compatible format)
    messages: list[dict[str, Any]] = field(default_factory=list)

    # Current investigation plan
    plan: AgentPlan | None = None

    # Evidence IDs collected from tool results
    evidence_ids: list[str] = field(default_factory=list)

    # Latest authoritative world version from the simulator
    latest_world_version: int | None = None

    # Rolling window of recent tool results (last 8)
    last_tool_results: list[dict[str, Any]] = field(default_factory=list)

    # Repeated-action tracking (kept for compatibility; LoopGuard owns the real state)
    repeated_actions: dict[str, int] = field(default_factory=dict)

    # Agent lifecycle status
    status: str = "running"

    # Approval decisions: list of dicts with keys: tool_name, granted, justification
    approval_history: list[dict[str, Any]] = field(default_factory=list)

    # Replan triggers: list of dicts with keys: trigger_status, revision, reason
    replan_history: list[dict[str, Any]] = field(default_factory=list)

    # Most recent verify_recovery evidence ID (must be cited in close_incident)
    last_verify_evidence_id: str | None = None

    def observe_result(self, result: dict[str, Any]) -> None:
        """Update state from a simulator tool result."""
        evidence = result.get("evidence_id")
        if evidence:
            self.evidence_ids.append(evidence)
            # Track verify_recovery evidence separately
            if result.get("tool") == "verify_recovery":
                self.last_verify_evidence_id = evidence

        version = result.get("world_version")
        if isinstance(version, int):
            self.latest_world_version = version

        self.last_tool_results.append(result)
        self.last_tool_results = self.last_tool_results[-8:]

    def record_approval(
        self,
        tool_name: str,
        granted: bool,
        justification: str = "",
    ) -> None:
        """Record a human approval decision."""
        self.approval_history.append(
            {"tool_name": tool_name, "granted": granted, "justification": justification}
        )

    def record_replan(self, trigger_status: str, revision: int, reason: str) -> None:
        """Record a replan event for tracing and analysis."""
        self.replan_history.append(
            {"trigger_status": trigger_status, "revision": revision, "reason": reason}
        )

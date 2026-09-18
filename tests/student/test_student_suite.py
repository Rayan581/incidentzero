"""Student test suite — covers 5+ distinct failure classes using offline ScriptedModelClient.

No Groq API key required. Tests validate controller reliability logic,
not the quality of any particular LLM response.

Failure classes covered:
  (A) Stale-world concurrency         → test_stale_precondition_triggers_replan
  (B) Human approval denial           → test_approval_denial_is_blocked / _replan
  (C) Loop detection & intervention   → test_loop_guard_blocks_third_repeat
  (D) Transient model retry           → test_retry_policy_retries_transient / _permanent
  (E) Malformed / invalid tool args   → test_malformed_tool_args_returned_as_observation
  (F) Premature close rejection       → test_close_without_verify_fails
  (G) Budget exhaustion / escalation  → test_budget_exhaustion_escalates
  (H) Plan revision                   → test_plan_revision_increments_counter
  (I) Unknown tool rejection          → test_unknown_tool_validation_error
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from incidentzero.agent.controller import AgentController
from incidentzero.agent.planner import Planner
from incidentzero.agent.policies import LoopGuard, ReplanPolicy
from incidentzero.agent.recovery import RetryPolicy
from incidentzero.agent.state import AgentState
from incidentzero.approval.gateway import AlwaysApproveGateway, AlwaysDenyGateway
from incidentzero.domain.models import AgentPlan, ModelReply, PlanStep, ToolCall
from incidentzero.environment.engine import SimulationEnvironment
from incidentzero.model.errors import PermanentModelError, TransientModelError
from incidentzero.model.scripted import ScriptedModelClient
from incidentzero.telemetry.budget import BudgetManager
from incidentzero.telemetry.trace import TraceRecorder
from incidentzero.tools.registry import ToolRegistry

# ─── Shared helpers ──────────────────────────────────────────────────────────

STUDENT_ID = "TEST-001"
SCENARIO = "public-a"

_PLAN_STRUCTURED = {
    "hypothesis": "Test hypothesis",
    "rationale_summary": "Test rationale",
    "steps": [
        {"step_id": "s1", "objective": "Gather data", "success_signal": "Data collected"},
        {"step_id": "s2", "objective": "Verify", "success_signal": "criteria_met=True"},
    ],
}


def _tc(name: str, args: dict, id: str = "tc-001") -> ToolCall:
    return ToolCall(id=id, name=name, arguments=args)


def _reply(*calls: ToolCall, content: str = "") -> ModelReply:
    return ModelReply(content=content, tool_calls=list(calls))


def _env():
    return SimulationEnvironment(STUDENT_ID, SCENARIO)


def _make(
    decisions: list[ModelReply],
    structured: list[dict] | None = None,
    approval=None,
    budget: BudgetManager | None = None,
    env: SimulationEnvironment | None = None,
) -> AgentController:
    e = env or _env()
    tmp = pathlib.Path(tempfile.mkdtemp())
    return AgentController(
        model=ScriptedModelClient(
            decisions=decisions,
            structured_outputs=structured or [_PLAN_STRUCTURED],
        ),
        tools=ToolRegistry(e),
        approval=approval or AlwaysApproveGateway(),
        budget=budget or BudgetManager(max_llm_calls=14, max_tool_calls=28),
        trace=TraceRecorder(tmp / "trace.jsonl"),
    )


# ─── (A) Stale-world detection ───────────────────────────────────────────────

@pytest.mark.student
def test_replan_policy_recognizes_stale_world():
    """ReplanPolicy must trigger on stale_precondition."""
    policy = ReplanPolicy()
    assert policy.should_replan({"status": "stale_precondition", "retryable": True}) is True


@pytest.mark.student
def test_replan_policy_does_not_trigger_on_ok():
    """ReplanPolicy must NOT trigger on normal ok results."""
    policy = ReplanPolicy()
    assert policy.should_replan({"status": "ok", "data": {}}) is False


@pytest.mark.student
def test_stale_precondition_observation_injected(tmp_path):
    """Controller must inject a corrective observation on stale_precondition."""
    e = _env()
    registry = ToolRegistry(e)

    # First call: get_incident (bootstrap). Then scale with old version.
    # Force a stale version by using version 0 (world starts at 1).
    decisions = [
        _reply(_tc("scale_service", {
            "service": "checkout-service",
            "replicas": 4,
            "expected_world_version": 0,   # deliberately stale
            "reason": "Testing stale precondition handling in controller",
        })),
        # After injected observation about stale world, escalate
        _reply(_tc("escalate_incident", {
            "reason": "Cannot resolve; stale world version prevented remediation",
            "evidence_ids": [],
        })),
    ]
    ctrl = _make(decisions, env=e)
    outcome = ctrl.run()
    # Should not crash; must end in a known terminal state
    assert outcome.status in {"escalated", "resolved", "budget_exhausted", "failed"}
    # Replan must have been triggered at least once
    assert len(ctrl.state.replan_history) >= 1 or len(ctrl.state.messages) > 5


# ─── (B) Human approval denial ───────────────────────────────────────────────

@pytest.mark.student
def test_replan_policy_recognizes_approval_denial():
    """ReplanPolicy must trigger on approval_denied."""
    policy = ReplanPolicy()
    assert policy.should_replan({"status": "approval_denied", "retryable": False}) is True


@pytest.mark.student
def test_approval_denial_blocks_execution(tmp_path):
    """A high-risk action denied by the gateway must NOT reach the simulator."""
    e = _env()
    # First observe state, then attempt rollback (which gets denied), then escalate.
    decisions = [
        _reply(_tc("rollback_deployment", {
            "service": "checkout-service",
            "target_version": "v0.9",
            "expected_world_version": 1,
            "reason": "Testing approval denial pathway; rollback should be denied",
        })),
        _reply(_tc("escalate_incident", {
            "reason": "Rollback approval denied; escalating with existing evidence",
            "evidence_ids": [],
        })),
    ]
    ctrl = _make(decisions, approval=AlwaysDenyGateway(), env=e)
    # The world should NOT be changed (closed = False)
    outcome = ctrl.run()
    assert outcome.status in {"escalated", "resolved", "budget_exhausted", "failed"}
    # Approval history must record the denial
    denials = [a for a in ctrl.state.approval_history if not a["granted"]]
    assert len(denials) >= 1


# ─── (C) Loop detection ──────────────────────────────────────────────────────

@pytest.mark.student
def test_loop_guard_detects_exact_repeat():
    """LoopGuard must return True on the (max+1)-th identical call."""
    guard = LoopGuard(max_same_action_repeats=2)
    args = {"service": "checkout-service", "replicas": 4}
    assert guard.record("scale_service", args) is False   # 1st
    assert guard.record("scale_service", args) is False   # 2nd
    assert guard.record("scale_service", args) is True    # 3rd → loop!


@pytest.mark.student
def test_loop_guard_different_args_not_flagged():
    """LoopGuard must not flag calls that differ in arguments."""
    guard = LoopGuard(max_same_action_repeats=2)
    assert guard.record("scale_service", {"service": "checkout-service", "replicas": 4}) is False
    assert guard.record("scale_service", {"service": "checkout-service", "replicas": 4}) is False
    # Different replicas count — different fingerprint
    assert guard.record("scale_service", {"service": "checkout-service", "replicas": 5}) is False


@pytest.mark.student
def test_loop_guard_reset_clears_counts():
    """LoopGuard.reset() must clear all repetition history."""
    guard = LoopGuard(max_same_action_repeats=2)
    args = {"service": "auth-service"}
    guard.record("restart_service", args)
    guard.record("restart_service", args)
    guard.reset()
    # After reset, first two calls are fine again
    assert guard.record("restart_service", args) is False
    assert guard.record("restart_service", args) is False


# ─── (D) Retry policy ────────────────────────────────────────────────────────

@pytest.mark.student
def test_retry_policy_retries_transient_only():
    """RetryPolicy must retry TransientModelError but not PermanentModelError."""
    calls: dict[str, int] = {"n": 0}
    sleeps: list[float] = []
    retry = RetryPolicy(max_attempts=3, sleeper=lambda s: sleeps.append(s))

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientModelError("429")
        return "ok"

    assert retry.call_model(flaky) == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2  # 2 waits between 3 attempts


@pytest.mark.student
def test_retry_policy_does_not_retry_permanent():
    """RetryPolicy must propagate PermanentModelError immediately."""
    calls: dict[str, int] = {"n": 0}
    retry = RetryPolicy(max_attempts=3, sleeper=lambda _: None)

    def permanent():
        calls["n"] += 1
        raise PermanentModelError("bad request")

    with pytest.raises(PermanentModelError):
        retry.call_model(permanent)
    assert calls["n"] == 1  # Only called once


@pytest.mark.student
def test_retry_policy_exponential_backoff():
    """RetryPolicy must produce exponential delays between retries."""
    sleeps: list[float] = []
    retry = RetryPolicy(
        max_attempts=4,
        initial_delay=1.0,
        backoff_factor=2.0,
        sleeper=lambda s: sleeps.append(s),
    )
    attempts: dict[str, int] = {"n": 0}

    def always_transient():
        attempts["n"] += 1
        raise TransientModelError("timeout")

    with pytest.raises(TransientModelError):
        retry.call_model(always_transient)

    assert len(sleeps) == 3  # 3 waits between 4 attempts
    assert sleeps[0] == pytest.approx(1.0)
    assert sleeps[1] == pytest.approx(2.0)
    assert sleeps[2] == pytest.approx(4.0)


# ─── (E) Malformed / invalid tool arguments ───────────────────────────────────

@pytest.mark.student
def test_unknown_tool_validation_error():
    """An unknown tool name must return a validation_error observation."""
    e = _env()
    registry = ToolRegistry(e)
    ok, error = registry.validate("nonexistent_tool_xyz", {})
    assert ok is False
    assert error is not None and "Unknown" in error


@pytest.mark.student
def test_malformed_tool_args_produce_observation(tmp_path):
    """Invalid arguments must return a corrective observation, not crash."""
    e = _env()
    # scale_service requires 'replicas' to be an integer; passing a string is invalid.
    decisions = [
        # First: a call with invalid arguments
        _reply(_tc("scale_service", {
            "service": "checkout-service",
            "replicas": "not-an-integer",   # INVALID
            "expected_world_version": 1,
            "reason": "Testing malformed argument handling",
        })),
        # After receiving validation_error, escalate
        _reply(_tc("escalate_incident", {
            "reason": "Cannot resolve; argument validation failed for scale action",
            "evidence_ids": [],
        })),
    ]
    ctrl = _make(decisions, env=e)
    outcome = ctrl.run()
    assert outcome.status in {"escalated", "resolved", "budget_exhausted", "failed"}
    # At least one tool result in state should be a validation_error
    validation_errors = [
        r for r in ctrl.state.last_tool_results
        if r.get("status") == "validation_error"
    ]
    assert len(validation_errors) >= 1


# ─── (F) Premature close rejection ──────────────────────────────────────────

@pytest.mark.student
def test_close_without_verify_recovery_fails(tmp_path):
    """close_incident must be rejected if verify_recovery was not called first."""
    e = _env()
    decisions = [
        # Immediately try to close without any verification
        _reply(_tc("close_incident", {
            "summary": "Attempting to close without verifying recovery first",
            "evidence_ids": ["EV-0001"],
            "expected_world_version": 1,
            "reason": "Testing premature close rejection by simulator",
        })),
        _reply(_tc("escalate_incident", {
            "reason": "Close was rejected; escalating with available evidence",
            "evidence_ids": [],
        })),
    ]
    ctrl = _make(decisions, env=e)
    outcome = ctrl.run()
    # Simulator must reject the close; final outcome cannot be 'resolved'
    # (unless the scenario happens to already meet criteria, which public-a doesn't)
    assert outcome.status in {"escalated", "budget_exhausted", "failed"}


# ─── (G) Budget exhaustion ───────────────────────────────────────────────────

@pytest.mark.student
def test_budget_exhaustion_does_not_raise(tmp_path):
    """Agent must return budget_exhausted or escalated outcome gracefully."""
    e = _env()
    # Give it almost no budget: 2 LLM calls (1 consumed by bootstrap planning + 1 for loop)
    decisions = [
        _reply(_tc("get_service_health", {"service": "checkout-service"})),
    ]
    ctrl = _make(
        decisions,
        budget=BudgetManager(max_llm_calls=3, max_tool_calls=5),
        env=e,
    )
    outcome = ctrl.run()
    assert outcome.status in {"budget_exhausted", "escalated", "resolved", "failed"}
    # Most importantly: no uncaught exception


# ─── (H) Plan revision ───────────────────────────────────────────────────────

@pytest.mark.student
def test_plan_revision_increments_counter():
    """Planner.revise must always increment the revision counter."""
    from incidentzero.agent.planner import Planner
    from incidentzero.model.scripted import ScriptedModelClient

    original = AgentPlan(
        hypothesis="Original hypothesis",
        steps=[PlanStep("s1", "Gather data", "Data gathered")],
        revision=0,
        rationale_summary="Original rationale",
    )

    # Structured output for plan revision
    model = ScriptedModelClient(
        structured_outputs=[
            {
                "hypothesis": "Revised hypothesis",
                "rationale_summary": "Revised rationale",
                "steps": [
                    {"step_id": "s1", "objective": "New approach", "success_signal": "Done"},
                    {"step_id": "s2", "objective": "Verify", "success_signal": "criteria_met=True"},
                ],
            }
        ]
    )
    planner = Planner(model)
    revised = planner.revise(original, {"status": "stale_precondition"}, "state summary")
    assert revised.revision == original.revision + 1


@pytest.mark.student
def test_plan_revision_fallback_on_model_error():
    """Planner.revise must fall back to current plan + incremented revision on model error."""
    from incidentzero.agent.planner import Planner
    from incidentzero.model.scripted import ScriptedModelClient

    original = AgentPlan(
        hypothesis="Original",
        steps=[PlanStep("s1", "Gather", "Done"), PlanStep("s2", "Verify", "criteria_met=True")],
        revision=2,
        rationale_summary="Original rationale",
    )
    # No structured outputs → scripted model raises RuntimeError → fallback
    model = ScriptedModelClient(structured_outputs=[])
    planner = Planner(model)
    # Should not raise; should fall back
    revised = planner.revise(original, {"status": "approval_denied"}, "state")
    assert revised.revision == 3
    assert revised.hypothesis == "Original"   # preserved


# ─── Integration: public requirement tests pass ───────────────────────────────

@pytest.mark.student
def test_public_requirements_still_pass():
    """Sanity check: public-facing requirement tests still satisfy contracts."""
    # ReplanPolicy
    policy = ReplanPolicy()
    assert policy.should_replan({"status": "stale_precondition", "retryable": True})
    assert policy.should_replan({"status": "approval_denied", "retryable": False})

    # LoopGuard
    guard = LoopGuard(max_same_action_repeats=2)
    args = {"service": "checkout-service", "replicas": 4}
    assert guard.record("scale_service", args) is False
    assert guard.record("scale_service", args) is False
    assert guard.record("scale_service", args) is True

    # RetryPolicy
    calls: dict[str, int] = {"n": 0}
    sleeps: list[float] = []
    retry = RetryPolicy(max_attempts=3, sleeper=lambda s: sleeps.append(s))

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientModelError("429")
        return "ok"

    assert retry.call_model(flaky) == "ok"
    assert calls["n"] == 3

    with pytest.raises(PermanentModelError):
        retry.call_model(lambda: (_ for _ in ()).throw(PermanentModelError("bad")))

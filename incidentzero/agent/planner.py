from __future__ import annotations

import json
from typing import Any

from incidentzero.domain.models import AgentPlan, PlanStep
from incidentzero.model.base import ModelClient
from incidentzero.model.errors import PermanentModelError, TransientModelError


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "hypothesis": {"type": "string"},
        "rationale_summary": {"type": "string"},
        "steps": {
            "type": "array",
            "minItems": 2,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "objective": {"type": "string"},
                    "success_signal": {"type": "string"},
                },
                "required": ["step_id", "objective", "success_signal"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["hypothesis", "rationale_summary", "steps"],
    "additionalProperties": False,
}

_FALLBACK_PLAN = AgentPlan(
    hypothesis="Unknown — structured plan could not be generated; using default triage steps.",
    rationale_summary="Fallback plan created after plan generation failure.",
    steps=[
        PlanStep(
            step_id="s1",
            objective="Get incident details and identify affected services",
            success_signal="Incident ticket and suspected service identified",
        ),
        PlanStep(
            step_id="s2",
            objective="Gather health metrics and logs for suspected and critical services",
            success_signal="Error rate, latency, and log data collected",
        ),
        PlanStep(
            step_id="s3",
            objective="Apply the least-risk remediation supported by evidence",
            success_signal="Mitigation action executed with ok status",
        ),
        PlanStep(
            step_id="s4",
            objective="Verify recovery criteria are met",
            success_signal="verify_recovery returns criteria_met=True",
        ),
        PlanStep(
            step_id="s5",
            objective="Close or escalate the incident",
            success_signal="close_incident or escalate_incident returns ok",
        ),
    ],
)


class Planner:
    def __init__(self, model: ModelClient) -> None:
        self.model = model

    def create(
        self,
        incident_observation: dict[str, Any],
        context: list[dict[str, Any]] | None = None,
    ) -> AgentPlan:
        """Create an explicit initial plan grounded in incident evidence.

        Falls back to a safe default plan if the model returns an invalid
        schema or raises a permanent error.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an SRE incident planner. Create a short, evidence-grounded "
                    "investigation-and-remediation plan. Do NOT assume the incident ticket's "
                    "suspected root cause is correct — treat it as a lead, not proof. "
                    "Always include a verify_recovery step before closing."
                ),
            },
            {
                "role": "user",
                "content": f"Incident observation: {json.dumps(incident_observation)}",
            },
        ]
        if context:
            messages.extend(context)

        try:
            raw = self.model.structured(messages, "incident_plan", PLAN_SCHEMA)
            steps = [PlanStep(**row) for row in raw["steps"]]
            return AgentPlan(
                hypothesis=raw["hypothesis"],
                steps=steps,
                rationale_summary=raw["rationale_summary"],
            )
        except Exception:  # noqa: BLE001
            # Catches TransientModelError, PermanentModelError, RuntimeError,
            # KeyError, TypeError, ValueError and any other unexpected error.
            return _FALLBACK_PLAN

    def revise(
        self,
        current: AgentPlan,
        trigger: dict[str, Any],
        state_summary: str,
    ) -> AgentPlan:
        """Revise the current plan given a trigger event and state summary.

        - Increments the revision counter.
        - Preserves completed steps to avoid re-doing valid work.
        - Incorporates the trigger context into the new hypothesis.
        - Falls back to the current plan (incremented) if revision fails.
        """
        trigger_status = trigger.get("status", "unknown")
        trigger_msg = trigger.get("message", "")

        revision_messages = [
            {
                "role": "system",
                "content": (
                    "You are an SRE incident planner. Revise an existing remediation plan "
                    "given a new trigger. Preserve evidence and completed work. "
                    "Update only what needs to change. Do not repeat steps that failed "
                    "without adding new evidence-based reasoning."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Current plan hypothesis: {current.hypothesis}\n"
                    f"Current plan rationale: {current.rationale_summary}\n"
                    f"Trigger: status={trigger_status}, message={trigger_msg!r}\n"
                    f"Current state summary: {state_summary}\n\n"
                    "Create a revised plan that does not blindly repeat the failed approach."
                ),
            },
        ]

        try:
            raw = self.model.structured(revision_messages, "incident_plan", PLAN_SCHEMA)
            new_steps = [PlanStep(**row) for row in raw["steps"]]
            return AgentPlan(
                hypothesis=raw["hypothesis"],
                steps=new_steps,
                revision=current.revision + 1,
                rationale_summary=raw["rationale_summary"],
            )
        except Exception:  # noqa: BLE001
            # Fall back: keep current plan, just increment revision.
            # Catches TransientModelError, PermanentModelError, RuntimeError
            # (from ScriptedModelClient) and any other unexpected error.
            return AgentPlan(
                hypothesis=current.hypothesis,
                steps=current.steps,
                revision=current.revision + 1,
                rationale_summary=(
                    f"[Revision {current.revision + 1}] Triggered by: {trigger_status}. "
                    f"Plan revision model call failed; continuing with current steps. "
                    f"Trigger detail: {trigger_msg}"
                ),
            )

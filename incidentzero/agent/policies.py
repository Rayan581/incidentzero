from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from incidentzero.domain.models import RiskLevel


class RiskPolicy:
    def __init__(self, config_path: str | Path = "configs/risk_policy.json") -> None:
        self.mapping = json.loads(Path(config_path).read_text(encoding="utf-8"))

    def risk(self, tool_name: str) -> RiskLevel:
        return RiskLevel(self.mapping.get(tool_name, "critical"))

    def requires_human_approval(self, tool_name: str) -> bool:
        return self.risk(tool_name) in {RiskLevel.HIGH, RiskLevel.CRITICAL}


class ReplanPolicy:
    """Classifies tool results and determines whether the current plan
    should be revised before continuing.

    Distinct failure classes:
    - stale_precondition  → world moved under us; re-observe then replan.
    - approval_denied     → human blocked the action; replan with that constraint.
    - non-retryable error → action failed permanently; replan or escalate.
    - verify failed       → remediation did not achieve criteria; replan.

    We do NOT replan for:
    - transient errors (the retry policy handles those before we get here).
    - successful ok results (including partial results that are still usable).
    """

    def should_replan(self, tool_result: dict[str, Any]) -> bool:
        status = tool_result.get("status", "")

        # World moved under us: re-observe before acting again.
        if status == "stale_precondition":
            return True

        # Human approver denied the action.
        if status == "approval_denied":
            return True

        # Non-retryable permanent errors: action cannot succeed as-is.
        if status == "error":
            retryable = tool_result.get("retryable", False)
            if not retryable:
                return True

        # verify_recovery returned criteria_met=False → remediation failed.
        data = tool_result.get("data") or {}
        if isinstance(data, dict) and "criteria_met" in data:
            if data["criteria_met"] is False:
                return True

        return False


class LoopGuard:
    """Detects when the exact same action has been repeated too many times.

    Uses a stable canonical fingerprint (SHA-256 of the sorted JSON
    representation of (action_name, arguments)) to identify identical
    calls, regardless of argument ordering in dicts.
    """

    def __init__(self, max_same_action_repeats: int = 2) -> None:
        self.max_same_action_repeats = max_same_action_repeats
        self._counts: dict[str, int] = {}

    def _fingerprint(self, action_name: str, arguments: dict[str, Any]) -> str:
        """Produce a stable, order-independent fingerprint for an action call."""
        canonical = json.dumps(
            {"action": action_name, "args": arguments},
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def record(self, action_name: str, arguments: dict[str, Any]) -> bool:
        """Record an action and return True when it has repeated too often.

        Returns True on the call that *exceeds* max_same_action_repeats
        (i.e. the 3rd identical call when max=2).
        Returns False if the action is still within allowable repetitions.
        """
        fp = self._fingerprint(action_name, arguments)
        count = self._counts.get(fp, 0) + 1
        self._counts[fp] = count
        return count > self.max_same_action_repeats

    def reset(self) -> None:
        """Clear all repetition counts (call when a meaningful plan revision occurs)."""
        self._counts.clear()

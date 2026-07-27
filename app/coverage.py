"""Status coverage ledger — which terminal statuses and failure classes have ever actually
been produced.

This exists because of a specific mistake worth not repeating. At M1 the hard gate "no run
is ever both wrong and marked verified" appeared to pass. It had not passed: the executor
contained no code path that could reach a success status at all, so the gate was
*unreachable*, not satisfied. An unreachable path is indistinguishable from a working one
until the day it is needed.

So every value in the two closed sets is declared here with the milestone at which it
becomes reachable, and the ledger records the first run that actually produced it. A value
that is due and unobserved is a failing gate. A value observed only from the regression
suite says so, rather than being presented as if a real run had produced it.
"""

from __future__ import annotations

from typing import Any

from app.models import FailureClass, TerminalStatus
from app.store import Store

#: Milestone at which each value first becomes producible. Ordered, so "due by now" is a
#: comparison rather than a judgement call.
MILESTONES: tuple[str, ...] = ("M1", "M2", "M3", "M4", "M5", "M6", "M7")

STATUS_DUE: dict[TerminalStatus, str] = {
    TerminalStatus.UNSUPPORTED: "M1",
    TerminalStatus.BLOCKED: "M1",
    TerminalStatus.UNVERIFIED: "M1",
    TerminalStatus.FAILED: "M1",
    TerminalStatus.SUCCEEDED_VERIFIED: "M2",
    TerminalStatus.NO_RESULT_VERIFIED: "M2",
    TerminalStatus.PARTIAL: "M2",
}

FAILURE_DUE: dict[FailureClass, str] = {
    FailureClass.POLICY_REFUSED: "M1",
    FailureClass.QUEUE_FULL: "M1",
    FailureClass.SESSION_QUOTA: "M2",
    FailureClass.LOCATOR_NOT_FOUND: "M2",
    FailureClass.POSTCONDITION_UNMET: "M2",
    FailureClass.VERIFICATION_MISMATCH: "M2",
    FailureClass.REQUIRED_ACTION_SKIPPED: "M2",
    FailureClass.BUDGET_EXHAUSTED: "M2",
    FailureClass.TIMEOUT: "M2",
    FailureClass.ROBOTS_DISALLOWED: "M2",
    FailureClass.SITE_UNAVAILABLE: "M2",
    FailureClass.INTERNAL_ERROR: "M2",
    # Nothing calls a model before M3, so these cannot be produced honestly yet.
    FailureClass.PROVIDER_QUOTA: "M3",
    FailureClass.PROVIDER_ERROR: "M3",
    FailureClass.TOKEN_BUDGET_EXHAUSTED: "M3",
    FailureClass.CONTEXT_BUDGET_EXCEEDED: "M3",
    # The injection defence is demonstrated at M6; the page it is demonstrated on exists now.
    FailureClass.INJECTION_DETECTED: "M6",
}


class CoverageLedger:
    """Reads and writes the ledger. Recording is a side effect of terminating a run, so it
    cannot drift from what the product actually did."""

    def __init__(self, store: Store, current_milestone: str = "M2") -> None:
        self._store = store
        self.current = current_milestone

    def record(self, *, status: TerminalStatus, failure: FailureClass | None,
               run_id: str, task: str, origin: str = "run") -> None:
        self._store.record_status_coverage(
            status.value, failure.value if failure else "", run_id, task, origin)

    def _due(self, milestone: str) -> bool:
        return MILESTONES.index(milestone) <= MILESTONES.index(self.current)

    def report(self) -> dict[str, Any]:
        seen = self._store.status_coverage()
        by_status: dict[str, list[dict[str, Any]]] = {}
        by_failure: dict[str, list[dict[str, Any]]] = {}
        for row in seen:
            by_status.setdefault(row["terminal_status"], []).append(row)
            if row["failure_class"]:
                by_failure.setdefault(row["failure_class"], []).append(row)

        def rows(due_map, observed):
            out = []
            for value, milestone in due_map.items():
                hits = observed.get(value.value, [])
                first = min(hits, key=lambda r: r["first_seen_at"]) if hits else None
                out.append({
                    "value": value.value,
                    "due_at": milestone,
                    "due_now": self._due(milestone),
                    "observed": bool(hits),
                    "origin": first["origin"] if first else None,
                    "first_run_id": first["first_run_id"] if first else None,
                    "first_seen_at": first["first_seen_at"] if first else None,
                    "count": sum(r["n"] for r in hits),
                    "overdue": self._due(milestone) and not hits,
                })
            return out

        statuses = rows(STATUS_DUE, by_status)
        failures = rows(FAILURE_DUE, by_failure)
        overdue = [r["value"] for r in statuses + failures if r["overdue"]]
        # An empty ledger must not read as a passing gate: with nothing declared and
        # nothing observed there would be no overdue rows either (A11.7).
        observed = [r for r in statuses + failures if r["observed"]]
        return {
            "milestone": self.current,
            "terminal_status": statuses,
            "failure_class": failures,
            "overdue": overdue,
            "gate_passes": bool(observed) and not overdue,
            "note": ("A value due at or before the current milestone and never observed is "
                     "an unreachable code path, which is how a gate passes without ever "
                     "having been tested."),
        }

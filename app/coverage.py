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

from app.buildstate import MILESTONE
from app.models import FailureClass, TerminalStatus
from app.store import Store

#: Milestone at which each value first becomes producible. Ordered, so "due by now" is a
#: comparison rather than a judgement call.
MILESTONES: tuple[str, ...] = ("M1", "M2", "M3", "M4", "M5", "M6", "M7")

if MILESTONE not in MILESTONES:
    raise RuntimeError(
        f"The build says it is at milestone {MILESTONE}, which is not one of {MILESTONES}. "
        f"This ledger decides what is overdue by comparing the two.")

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
    # Our own per-call output cap, which the model's thinking tokens share (A17.8). It was
    # first produced by a live run at M4, wearing `internal_error`.
    FailureClass.OUTPUT_TRUNCATED: "M4",
}

#: Values whose code path was deliberately **not built**, with what is missing. Kept apart
#: from the milestone map on purpose: a milestone is a statement that something is coming,
#: and reading "due at M6 / not due yet" against a value that was cut says the schedule is
#: intact when the work was dropped. That is optimistic in exactly the direction this page
#: exists to prevent, and it happened here.
NOT_BUILT: dict[FailureClass, str] = {
    FailureClass.INJECTION_DETECTED:
        "No injection detector was built and none is scheduled. The safety split was cut, "
        "not deferred. The value stays declared because the taxonomy is closed by the "
        "spec — what is reported here is that no code path reaches it.",
}


class CoverageLedger:
    """Reads and writes the ledger. Recording is a side effect of terminating a run, so it
    cannot drift from what the product actually did."""

    def __init__(self, store: Store, current_milestone: str = MILESTONE) -> None:
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

        def rows(due_map, observed, not_built=None):
            not_built = not_built or {}
            # Declared values come from two places now: those with a milestone, and those
            # with a reason they have none.
            declared = list(due_map.items()) + [(v, None) for v in not_built]
            out = []
            for value, milestone in declared:
                hits = observed.get(value.value, [])
                first = min(hits, key=lambda r: r["first_seen_at"]) if hits else None
                due_now = self._due(milestone) if milestone else False
                out.append({
                    "value": value.value,
                    "due_at": milestone,
                    "due_now": due_now,
                    # A cut path carries no milestone at all. `not_built` is the reason it
                    # will not arrive, so the page can say that instead of "not due yet".
                    "not_built": not_built.get(value),
                    "observed": bool(hits),
                    "origin": first["origin"] if first else None,
                    "first_run_id": first["first_run_id"] if first else None,
                    "first_seen_at": first["first_seen_at"] if first else None,
                    "count": sum(r["n"] for r in hits),
                    "overdue": due_now and not hits,
                })
            return out

        statuses = rows(STATUS_DUE, by_status)
        failures = rows(FAILURE_DUE, by_failure, NOT_BUILT)
        overdue = [r["value"] for r in statuses + failures if r["overdue"]]
        not_built = [r["value"] for r in statuses + failures if r["not_built"]]
        # An empty ledger must not read as a passing gate: with nothing declared and
        # nothing observed there would be no overdue rows either (A11.7).
        observed = [r for r in statuses + failures if r["observed"]]
        return {
            "milestone": self.current,
            "terminal_status": statuses,
            "failure_class": failures,
            "overdue": overdue,
            "not_built": not_built,
            "gate_passes": bool(observed) and not overdue,
            "note": ("A value due at or before the current milestone and never observed is "
                     "an unreachable code path, which is how a gate passes without ever "
                     "having been tested. A value listed under not_built is one whose code "
                     "path was dropped rather than scheduled; it has no milestone, and it "
                     "is never counted as overdue."),
        }

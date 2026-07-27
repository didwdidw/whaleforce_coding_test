"""Auditing the outcomes that are quiet, because every safety mechanism is also a hiding place.

Each control this system has added to fail closed — abstain when the page does not support
the goal, refuse when robots disallows, refuse to start without a persistent store — creates
an outcome that looks correct from the outside no matter why it happened. That is not an
argument against the controls; it is the cost of having them, and it has to be paid
somewhere.

OP-6 is the worked example. The reduced view dropped the one pagination link the task needed,
the model was shown a page with no pager, and it abstained. The abstention was correct about
what it had been given. Nothing downstream could tell it apart from a page that genuinely had
no pager, because both produce the same honest refusal. We only caught it because we knew the
answer. On a held-out case nobody knows the answer, and an abstention looks right forever.

So a quiet outcome is not reported on its own. It is reported together with whatever is in
the trace that could have caused it — specifically, evidence that *we* removed the answer
before anyone could act on it. That evidence already exists: reduction records what it
dropped and under which category (A7.3). What was missing was making a run-level conclusion
answer for it.

The audit deliberately does not change any status. It cannot make a run pass, and it does not
demote one; it attaches what a reader needs to stop treating a refusal as information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import FailureClass, Run, TerminalStatus

#: Outcomes whose entire content is an absence or a refusal. A wrong one of these is
#: indistinguishable from a right one without looking at how it was reached.
QUIET_STATUSES = {
    TerminalStatus.UNSUPPORTED,       # abstained, or refused as out of scope
    TerminalStatus.NO_RESULT_VERIFIED,  # asserted that there is nothing to find
    TerminalStatus.BLOCKED,           # refused by robots, quota or policy
}


@dataclass(frozen=True)
class Suspicion:
    """One reason a quiet outcome should not be read as clean."""

    code: str
    what: str
    why: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "what": self.what, "why": self.why,
                "evidence": self.evidence}


def _reductions(run: Run) -> list[dict[str, Any]]:
    return [t.detail["reduction"] for t in run.trace
            if isinstance(t.detail.get("reduction"), dict)]


def _checked_against_an_artifact(run: Run) -> bool:
    """Whether anything was re-extracted from a stored artifact.

    This is the line that decides how much the trimming evidence matters. Verification never
    runs against the reduced view (A7.4) — it re-reads the full stored page — so a verified
    absence has already been checked against something reduction cannot have damaged. An
    abstention has been checked against nothing at all: the reduced view is the only thing
    that was ever consulted, and the reduced view is exactly what may be at fault.
    """
    return bool(run.claims)


def audit(run: Run) -> list[Suspicion]:
    """What in this run's own trace undermines its quiet outcome."""
    if run.terminal_status not in QUIET_STATUSES:
        return []

    found: list[Suspicion] = []
    reductions = _reductions(run)
    verified_against_artifact = _checked_against_an_artifact(run)

    dropped_named = [r for r in reductions
                     if r.get("dropped", {}).get("interactive_goal_term_over_cap")]
    if dropped_named and not verified_against_artifact:
        total = sum(r["dropped"]["interactive_goal_term_over_cap"] for r in dropped_named)
        found.append(Suspicion(
            code="goal_named_element_dropped",
            what=f"Reduction dropped {total} element(s) that the goal itself names, across "
                 f"{len(dropped_named)} model call(s) in this run.",
            why="The outcome rests entirely on what the model was shown, and what the model "
                "was shown had already lost elements the task names. A refusal reached this "
                "way is a statement about our reduction, not about the page.",
            evidence={"calls_affected": len(dropped_named), "elements_dropped": total,
                      "rule_version": reductions[0].get("rule_version") if reductions else None}))

    dropped_regions = [r for r in reductions
                       if r.get("dropped", {}).get("anchor_region_over_cap")]
    if dropped_regions and not verified_against_artifact:
        found.append(Suspicion(
            code="anchor_region_dropped",
            what=f"Reduction dropped candidate anchor regions on "
                 f"{len(dropped_regions)} model call(s).",
            why="The region holding the value may never have been offered. Nothing here was "
                "re-read from the stored artifact, so no independent check contradicts it.",
            evidence={"calls_affected": len(dropped_regions)}))

    if (run.terminal_status is TerminalStatus.UNSUPPORTED
            and run.failure_class is FailureClass.POLICY_REFUSED
            and not reductions and not verified_against_artifact
            and any(t.kind.value == "navigate" and t.ok for t in run.trace)):
        found.append(Suspicion(
            code="refused_without_looking",
            what="The run reached a page and then refused without any reduced view being "
                 "produced.",
            why="A refusal that never examined the page it fetched cannot be attributed to "
                "the page.",
            evidence={}))

    if run.terminal_status is TerminalStatus.BLOCKED and (
            run.failure_class is FailureClass.ROBOTS_DISALLOWED):
        quoted = any(t.detail.get("matched_rule") or t.detail.get("robots")
                     for t in run.trace)
        if not quoted:
            found.append(Suspicion(
                code="refusal_rule_not_quoted",
                what="A policy refusal was recorded without the rule that produced it.",
                why="A refusal nobody can check against a quotable rule is a refusal that "
                    "cannot be told apart from a bug in our matcher.",
                evidence={}))

    return found


def annotate(run: Run) -> list[Suspicion]:
    """Attach the audit to the run, and make the explanation carry it.

    The explanation is the part a person actually reads, so a suspect refusal must not be
    able to read as a clean one there either.
    """
    found = audit(run)
    if not found:
        return []
    run.suspicions = [s.to_dict() for s in found]
    run.explanation = (
        f"{run.explanation}\n\n"
        f"This outcome is NOT a clean {run.terminal_status.value}: "
        + " ".join(f"{s.what} {s.why}" for s in found)
    ).strip()
    return found

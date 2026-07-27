"""A quiet outcome has to answer for what the trace says we may have removed.

Every control that fails closed also creates an outcome that looks correct from outside
regardless of why it happened. OP-6 is the worked example: the reduced view dropped the one
pagination link the task needed, and the model — shown a page with no pager — abstained. The
abstention was correct about what it had been given, and indistinguishable from a page that
genuinely had no pager.

We caught it because we knew the answer. On a held-out case nobody knows the answer, and the
abstention looks right forever. These tests are what makes the co-occurrence visible from
outside instead.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.models import (
    FailureClass, Run, RunState, StepKind, TerminalStatus, Tier, TraceEntry, new_id,
)
from app.suspicion import QUIET_STATUSES, annotate, audit


def _run(status: TerminalStatus, failure: FailureClass | None = None, *,
         dropped: dict | None = None, claims: list | None = None,
         navigated: bool = True) -> Run:
    run = Run(id=new_id("run"), task="page through the listing", tier=Tier.EXPERIMENTAL,
              state=RunState.DONE, terminal_status=status, failure_class=failure,
              explanation="The planner abstained rather than acting on a guess.")
    run.claims = claims or []
    if navigated:
        run.add(TraceEntry(seq=1, kind=StepKind.NAVIGATE, summary="Navigate", ok=True))
    if dropped is not None:
        run.add(TraceEntry(
            seq=2, kind=StepKind.NOTE, summary="Model call (exploration) for step 1", ok=True,
            detail={"reduction": {"rule_version": "reduce/v1.3", "dropped": dropped,
                                  "kept": {"interactive": 60}}}))
    return run


# --- the signal itself -------------------------------------------------------------

def test_an_abstention_that_dropped_a_goal_named_element_is_not_clean():
    """The OP-6 case, as a run-level conclusion rather than a reducer statistic."""
    run = _run(TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
               dropped={"interactive_goal_term_over_cap": 3})

    found = audit(run)
    assert [s.code for s in found] == ["goal_named_element_dropped"]
    assert found[0].evidence["elements_dropped"] == 3


def test_the_explanation_itself_stops_reading_as_a_clean_refusal():
    """The explanation is the part a person actually reads, and the part an evaluator
    quotes. A marker that lives only in a JSON field is one nobody sees."""
    run = _run(TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
               dropped={"interactive_goal_term_over_cap": 1})
    annotate(run)

    assert "NOT a clean unsupported" in run.explanation
    assert run.suspicions and run.suspicions[0]["code"] == "goal_named_element_dropped"


def test_a_clean_abstention_stays_clean():
    """The audit has to be quiet when there is nothing, or it is noise and gets ignored."""
    run = _run(TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
               dropped={"interactive_over_cap": 34, "interactive_invisible": 2})

    assert audit(run) == []
    annotate(run)
    assert run.suspicions == []
    assert "NOT a clean" not in run.explanation


def test_a_successful_run_is_not_audited_at_all():
    """This is not a general quality signal. It exists for outcomes whose whole content is
    an absence, where being wrong and being right look identical."""
    run = _run(TerminalStatus.SUCCEEDED_VERIFIED,
               dropped={"interactive_goal_term_over_cap": 5})
    assert audit(run) == []


def test_trimming_does_not_undermine_a_result_that_was_re_read_from_the_artifact():
    """The distinction that decides how much the evidence weighs.

    Verification never runs against the reduced view — it re-reads the full stored page — so
    a verified absence has already been checked against something reduction cannot have
    damaged. An abstention has been checked against nothing at all.
    """
    verified_absence = _run(TerminalStatus.NO_RESULT_VERIFIED,
                            dropped={"interactive_goal_term_over_cap": 4},
                            claims=[{"name": "coverage_anchor", "ok": True}])
    assert audit(verified_absence) == []

    abstention = _run(TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                      dropped={"interactive_goal_term_over_cap": 4})
    assert audit(abstention)


def test_a_refusal_after_reaching_a_page_without_ever_looking_at_it_is_flagged():
    run = _run(TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED)
    assert [s.code for s in audit(run)] == ["refused_without_looking"]


def test_a_refusal_before_any_page_was_fetched_is_not_flagged():
    """Out-of-scope refusals happen before any network activity, and are exactly as clean
    as they look."""
    run = _run(TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED, navigated=False)
    assert audit(run) == []


def test_a_robots_refusal_must_carry_the_rule_that_produced_it():
    """A refusal nobody can check against a quotable rule cannot be told apart from a bug
    in our matcher — the same shape as the abstention problem, on the other control."""
    run = _run(TerminalStatus.BLOCKED, FailureClass.ROBOTS_DISALLOWED)
    assert "refusal_rule_not_quoted" in [s.code for s in audit(run)]

    run.trace[-1].detail["matched_rule"] = "Disallow: /__testhook__/"
    assert "refusal_rule_not_quoted" not in [s.code for s in audit(run)]


# --- the audit cannot be routed around ---------------------------------------------

def test_every_quiet_status_is_covered_by_the_audit():
    """A status added later without being classified would silently opt out."""
    from app.models import counts_as_success

    quiet_by_meaning = {TerminalStatus.UNSUPPORTED, TerminalStatus.BLOCKED,
                        TerminalStatus.NO_RESULT_VERIFIED}
    assert quiet_by_meaning <= QUIET_STATUSES
    # And the one quiet status that counts as a success is in scope, because a wrong
    # `no_result_verified` is the most expensive silent failure this system can produce.
    assert any(counts_as_success(s) for s in QUIET_STATUSES)


def test_no_run_can_end_without_passing_through_the_audit():
    """Structural, because the audit is only worth anything if it is unavoidable.

    `_terminate` is the single place a terminal status is assigned, and it is the single
    place the audit runs. A second assignment elsewhere would be a way out.
    """
    source = pathlib.Path("app/executor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assignments = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "terminal_status":
            parent_assign = isinstance(getattr(node, "ctx", None), ast.Store)
            if parent_assign:
                assignments.append(node.lineno)

    terminate = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
                     and n.name == "_terminate")
    span = range(terminate.lineno, (terminate.end_lineno or terminate.lineno) + 1)
    outside = [line for line in assignments if line not in span]
    assert not outside, (
        f"executor.py assigns terminal_status outside _terminate at lines {outside}; that "
        f"is a path on which a quiet outcome is never audited")

    assert "annotate(run)" in ast.get_source_segment(source, terminate)

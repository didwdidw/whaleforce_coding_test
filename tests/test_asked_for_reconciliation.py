"""Every planner is reconciled against what the task asked for (A28.2, A-84).

`asked_for_parts` was correct, tested over eleven task shapes — and wired to one of its
callers. `_plan_wiki_expand` compiles a postcondition from the same task text and was never
audited against it, so the two canonical OP-5 cases froze *"expand box 1 and report that it
is no longer collapsed"*, verified that one state transition, and returned
`succeeded_verified` for a question whose answer was sitting in the stored artifact.

So the subject here is **the reconciliation, over every path that compiles a postcondition**
— not any one parser. A test that shows `_plan_wiki_expand` claims a named group is a test
of the branch that always worked.
"""

from __future__ import annotations

import inspect

import pytest

from app.executor import Executor
from app.postcondition import ANSWERS_A_VALUE, Relation

DEV_04 = ("On the Wikipedia article for Apple Inc., expand the first collapsed box at the "
          "foot of the page and tell me its title and the label of its first row group.")
DEV_05 = ("On the Apple Inc. Wikipedia page, expand the second collapsed box and tell me "
          "how many entries are in its first row group.")

#: One task per route that compiles a postcondition, in the words a person would use. The
#: corpus is the audit: a planner added without reconciliation fails here rather than on a
#: deployment, which is where this one was found.
CORPUS = (
    DEV_04, DEV_05,
    "On the Wikipedia list of S&P 500 companies, sort the constituents table by 'Date "
    "added' newest first, and tell me the ticker symbol and company name of the row that "
    "ends up at the top.",
    "In the Poetry category on books.toscrape.com, open 'A Light in the Attic' and tell me "
    "its UPC.",
    "For 'A Light in the Attic' on books.toscrape.com, what does the product page say "
    "about availability?",
    "Go to books.toscrape.com, open the Nonfiction category, and tell me how many books it "
    "has in total and how many pages of results.",
    "Is there any book in the Poetry category on books.toscrape.com priced at £60.00 or "
    "more?",
    "Search the fixture catalogue for lantern",
    "Read page 2 of the fixture browse listing without clicking next",
    "Is any product in the fixture catalogue priced over £100?",
    "Dismiss the overlay on the fixture gated page and read the reference code, seed "
    "mu2-text",
    "On www.gutenberg.org, find the 'Science Fiction' bookshelf and tell me how many "
    "ebooks it lists.",
)


def _plan(task: str):
    ex = Executor.__new__(Executor)
    return ex._select_plan(task) or ex._undeclared_plan(task)


@pytest.mark.parametrize("task", [DEV_04, DEV_05])
def test_the_canonical_op5_tasks_freeze_a_claim_for_the_value_they_ask_for(task):
    """The defect, driven from the task string a user types.

    Before this, the frozen postcondition's only claim was `still_collapsed` — a state
    transition, verified honestly, and no answer to anything that was asked.
    """
    pc = _plan(task).postcondition
    assert pc.operation == "OP-5"
    parts = Executor.asked_for_parts(task)
    answering = [c for c in pc.claims if c.relation in ANSWERS_A_VALUE and not c.optional]
    assert len(answering) >= len(parts), (
        f"{len(parts)} value(s) asked for, {len(answering)} claim(s) that could carry one")
    assert all(c.relation is Relation.LOCATED_LABEL for c in answering)
    assert pc.inputs["asked_for"] == list(parts)
    # The state claim is still there: the fix adds what was missing, it does not trade one
    # kind of evidence for the other.
    assert "still_collapsed" in {c.name for c in pc.claims}
    assert "label_anchor" in pc.goal


@pytest.mark.parametrize("task", CORPUS)
def test_no_planner_leaves_an_asked_for_part_with_nothing_to_answer_it(task):
    """The audit that was never run. Every path that compiles a postcondition, checked
    against the rule, rather than the one path somebody remembered to wire."""
    plan = _plan(task)
    assert plan is not None, f"no plan at all for {task!r}"
    if not plan.postcondition.claims:
        pytest.skip("a plan with no claims is a policy demonstration, not an answer")
    parts = Executor.asked_for_parts(Executor._strip_directives(task))
    assert Executor.unanswered_parts(parts, plan.postcondition.claims) == ()


def test_every_planner_is_reached_through_the_reconciling_entry_points():
    """The structural half. A planner called from somewhere else is exactly how this
    defect happened, so a new one that skips the reconciliation fails here."""
    declared = inspect.getsource(Executor._declared_plan)
    for name in dir(Executor):
        if not name.startswith("_plan_"):
            continue
        assert f"self.{name}(" in declared or name == "_plan_generic", (
            f"{name} is not reached from _declared_plan, so nothing reconciles it")
    for entry in (Executor._select_plan, Executor._undeclared_plan):
        assert "_reconcile_asked_for" in inspect.getsource(entry), (
            f"{entry.__name__} returns a plan without reconciling it")


def test_a_state_transition_does_not_count_as_an_answer():
    """The rule underneath the fix, stated where it can fail on its own. `element_absent`
    evidences that a box opened; nobody asked whether a box was open."""
    from app.postcondition import ClaimSpec

    only_state = (ClaimSpec("still_collapsed", "collapsed marker of box 1",
                            Relation.ELEMENT_ABSENT, "boolean", container="//x"),)
    assert Executor.unanswered_parts(("its title",), only_state) == (0,)
    assert Executor.unanswered_parts(("its title", "its group"), only_state) == (0, 1)


def test_a_question_naming_a_label_is_answered_by_the_claim_bound_to_it():
    from app.postcondition import ClaimSpec

    fields = (ClaimSpec("upc", "UPC", Relation.TABLE_ROW_CELL, "text"),
              ClaimSpec("availability", "Availability", Relation.TABLE_ROW_CELL, "text"))
    assert Executor.unanswered_parts(("its UPC", "availability"), fields) == ()
    # Consumed as they are used: two questions cannot both be answered by the one field.
    assert Executor.unanswered_parts(("its UPC", "its UPC again", "a third thing"),
                                     fields) == (2,)


#: The expanded box as the reviewer found it in the stored artifact: `mw-collapsed` gone,
#: the title and the first group's label sitting there in the markup.
EXPANDED = (b'<div class="navbox"><div class="mw-collapsible navbox-inner">'
            b'<table><tr><th class="navbox-title">Apple Inc.</th></tr>'
            b'<tr><th class="navbox-group">Hardware</th><td>Mac</td></tr>'
            b'<tr><th>Title</th><td>Apple Inc. products</td></tr></table>'
            b'</div></div>')


def _expanded_run(store, plan):
    """A DEV-04 run that did everything except bind the values: it navigated, it clicked
    the toggle, and the box is open in the artifact. Everything the old build needed for
    `succeeded_verified`."""
    from app.models import Run, StepKind, Tier, TraceEntry, new_id

    run = Run(id=new_id("run"), task=DEV_04, tier=Tier.DECLARED)
    run.postcondition = plan.postcondition.to_dict()
    run.postcondition_hash = plan.postcondition.sha256
    target = plan.postcondition.target_url
    run.trace = [
        TraceEntry(seq=1, kind=StepKind.NAVIGATE, summary="Navigate to the article", ok=True,
                   detail={"url": target, "final_url": target,
                           "redirect_chain": [{"url": target, "status": 200}]}),
        TraceEntry(seq=2, kind=StepKind.CLICK, summary="Expand collapsed box 1", ok=True,
                   detail={"element": {"role": "link", "name": "show", "text": "show"}}),
    ]
    store.save_run(run)
    artifact = store.put_artifact(run.id, "dom:collapsible-1-expanded", EXPANDED,
                                  source_url=target, media_type="text/html")
    return run, artifact.id


def test_binding_only_the_state_transition_is_partial_and_partial_is_not_success(tmp_path):
    """What the deployment returned for DEV-04, run against the postcondition this build
    freezes for it: the box did open, the two asked-for values bound to nothing, and the
    run is `partial` — loud, and never counted as a success."""
    from app.models import FailureClass, TerminalStatus
    from app.store import Store
    from app.verifier import Verifier

    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    plan = _plan(DEV_04)
    run, artifact = _expanded_run(store, plan)

    verdict = Verifier(store).verify(run, artifact_id=artifact,
                                     candidate={"still_collapsed": True})

    assert verdict.status is TerminalStatus.PARTIAL
    assert verdict.status is not TerminalStatus.SUCCEEDED_VERIFIED
    assert verdict.failure_class is FailureClass.LOCATOR_NOT_FOUND
    assert verdict.counts_as_success is False
    assert "1 of 3" in verdict.explanation


def test_the_same_run_with_the_values_bound_is_a_success(tmp_path):
    """The other half: the fix demands an answer, it does not make the case unanswerable."""
    from app.models import TerminalStatus
    from app.store import Store
    from app.verifier import Verifier

    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    plan = _plan(DEV_04)
    run, artifact = _expanded_run(store, plan)

    verdict = Verifier(store).verify(run, artifact_id=artifact, candidate={
        "still_collapsed": True,
        "answer_1": "Apple Inc. products", "answer_1_anchor": "Title",
        "answer_2": "Mac", "answer_2_anchor": "Hardware"})

    assert verdict.status is TerminalStatus.SUCCEEDED_VERIFIED
    assert verdict.counts_as_success is True

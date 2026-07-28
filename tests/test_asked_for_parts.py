"""A postcondition carries every part the task asked for (A25.3, A-75).

Found on the deployed system, not by a split: a live experimental-tier request for *"UPC and
availability"* froze one unnamed claim with `required_actions: []`, verified the UPC, dropped
availability without a word, and returned `succeeded_verified`. S-5.2 already forbids
presenting a partial result as a success — an empty postcondition is how that prohibition
gets bypassed without anybody writing the word `partial`.

The parser is deliberately small and deliberately biased. How many things were asked for
decides whether a run may be called a success, so it is not decided by the component whose
answer is being graded; and where it is unsure it splits, because one part too many makes a
correct run `partial`, which is loud, and one too few drops a value in silence.
"""

from __future__ import annotations

import pytest

from app.executor import Executor
from app.postcondition import Relation

MDN = ("On developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/"
       "flat, tell me the Chrome version listed in the browser compatibility table.")


@pytest.mark.parametrize("task,parts", [
    ("On books.toscrape.com/x.html, open it and tell me its UPC and availability.",
     ("its UPC", "availability")),
    ("On example.org/x, what are the team name, wins and losses of the first row?",
     ("the team name", "wins", "losses of the first row")),
    (MDN, ("the Chrome version listed in the browser compatibility table",)),
    # "find X and tell me Y" asks for one thing and navigates to another. The asking starts
    # at the *last* verb, or every route to an answer would be counted as an answer.
    ("On www.gutenberg.org, find the Science Fiction bookshelf and tell me how many ebooks "
     "it lists.", ("ebooks it lists",)),
    ("On the-internet.herokuapp.com/dynamic_loading/2, click Start and tell me the text "
     "that appears.", ("the text that appears",)),
    # Two interrogatives is two values. The *first* is where the asking starts here, unlike
    # "…and tell me X", where the last reporting verb is — otherwise "how many pages and how
    # many results" loses the first half to the second.
    ("On example.org/x, how many pages and how many results are there?",
     ("pages", "results are there")),
    # No reporting verb and no interrogative: nothing marks where the asking starts, so
    # splitting would turn the leading clause into a claim about a site name.
    ("For 'A Light in the Attic' on books.toscrape.com, look at the product page.",
     ("For 'A Light in the Attic' on books.toscrape.com, look at the product page.",)),
])
def test_the_parts_a_task_asks_for(task, parts):
    assert Executor.asked_for_parts(task) == parts


def test_a_sentence_too_long_to_split_is_one_claim_not_five():
    """The conservative end. Splitting a paragraph is guessing, and the single claim still
    has to bind to a label in the artifact or the run does not succeed."""
    rambling = ("On example.org/x, tell me the name, the address, the phone number, "
                "the opening hours, the manager and the postcode.")
    assert len(Executor.asked_for_parts(rambling)) == 1


def test_a_two_part_task_freezes_two_claims_before_browsing():
    """The fix itself. One claim per part, named in the frozen postcondition, so a run that
    answers one of them cannot reach `succeeded_verified` by having nothing to fail."""
    plan = Executor._plan_generic(
        Executor.__new__(Executor),
        "On books.toscrape.com/catalogue/x.html, tell me its UPC and availability.")

    assert plan is not None
    pc = plan.postcondition
    assert [c.name for c in pc.claims] == ["answer_1", "answer_2"]
    assert all(c.relation is Relation.LOCATED_LABEL for c in pc.claims)
    assert all(not c.optional for c in pc.claims), (
        "an optional claim is a claim that can be skipped, which is the defect again")
    assert pc.inputs["asked_for"] == ["its UPC", "availability"]
    # The model is told what it has to produce, in the frozen goal rather than implicitly.
    assert "2 separate values" in pc.goal and "partial result" in pc.goal


def test_a_one_part_task_keeps_the_shape_every_earlier_run_recorded():
    plan = Executor._plan_generic(Executor.__new__(Executor), MDN)
    assert [c.name for c in plan.postcondition.claims] == ["answer"]
    assert "separate values" not in plan.postcondition.goal


def test_verifying_one_of_two_claims_is_partial_and_partial_is_not_success(tmp_path):
    """The rule that makes the extra claim worth freezing. `partial` already existed and was
    unreachable on this path, because there was never more than one claim to half-satisfy."""
    from app.models import FailureClass, Run, TerminalStatus, Tier, new_id
    from app.store import Store
    from app.verifier import Verifier

    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    task = "On books.toscrape.com/catalogue/x.html, tell me its UPC and availability."
    plan = Executor._plan_generic(Executor.__new__(Executor), task)
    run = Run(id=new_id("run"), task=task, tier=Tier.EXPERIMENTAL)
    run.postcondition = plan.postcondition.to_dict()
    run.postcondition_hash = plan.postcondition.sha256
    store.save_run(run)
    body = (b"<table><tr><th>UPC</th><td>a897fe39b1053632</td></tr>"
            b"<tr><th>Availability</th><td>In stock (22 available)</td></tr></table>")
    artifact = store.put_artifact(run.id, "dom:step-1", body,
                                 source_url="https://books.toscrape.com/catalogue/x.html",
                                 media_type="text/html")

    verdict = Verifier(store).verify(run, artifact_id=artifact.id, candidate={
        "answer_1": "a897fe39b1053632", "answer_1_anchor": "UPC"})

    assert verdict.status is TerminalStatus.PARTIAL
    assert verdict.failure_class is FailureClass.LOCATOR_NOT_FOUND
    assert verdict.counts_as_success is False
    assert "1 of 2" in verdict.explanation


def test_both_claims_verified_is_a_success(tmp_path):
    from app.models import Run, TerminalStatus, Tier, new_id
    from app.store import Store
    from app.verifier import Verifier

    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    task = "On books.toscrape.com/catalogue/x.html, tell me its UPC and availability."
    plan = Executor._plan_generic(Executor.__new__(Executor), task)
    run = Run(id=new_id("run"), task=task, tier=Tier.EXPERIMENTAL)
    run.postcondition = plan.postcondition.to_dict()
    run.postcondition_hash = plan.postcondition.sha256
    store.save_run(run)
    body = (b"<table><tr><th>UPC</th><td>a897fe39b1053632</td></tr>"
            b"<tr><th>Availability</th><td>In stock (22 available)</td></tr></table>")
    artifact = store.put_artifact(run.id, "dom:step-1", body,
                                 source_url="https://books.toscrape.com/catalogue/x.html",
                                 media_type="text/html")

    verdict = Verifier(store).verify(run, artifact_id=artifact.id, candidate={
        "answer_1": "a897fe39b1053632", "answer_1_anchor": "UPC",
        "answer_2": "In stock (22 available)", "answer_2_anchor": "Availability"})

    assert verdict.status is TerminalStatus.SUCCEEDED_VERIFIED
    assert verdict.counts_as_success is True

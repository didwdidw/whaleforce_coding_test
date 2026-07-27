"""Proof of absence on a promised site (XB-1 Mode B, A3.1/A3.2).

The dev split declares this case `T-DECLARED`, and nothing implemented it: a price question
about a books.toscrape category fell to the generic path, which has no way to prove coverage,
and failed. The gap was invisible because the fixture had an absence plan and the promised
site did not — the capability existed, on the site we wrote ourselves.

Two properties are worth more than the routing details. The coverage anchor may be the
listing's own result count, which is the exact form A3.2 names, and without which a category
that fits on one page could never be proven. And the run now states what it found, so the
verifier can disagree with it — a plan that only ever asserts absence cannot be caught
reading its own predicate backwards.
"""

from __future__ import annotations

import pytest

from app.executor import Executor
from app.models import FailureClass, TerminalStatus
from app.postcondition import AbsenceMode, ClaimSpec, Postcondition, Relation
from app.verifier import Verifier

POETRY = "Is there any book in the Poetry category on books.toscrape.com priced at £60.00 or more?"


# ---- reading the question -------------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("priced at £60.00 or more", (">=", 60.0)),
    ("priced over £60", (">", 60.0)),
    ("at least £25", (">=", 25.0)),
    ("under £15", ("<", 15.0)),
    ("£10 or less", ("<=", 10.0)),
    ("more expensive than £30", (">", 30.0)),
])
def test_the_comparison_comes_from_the_task(phrase, expected):
    """`£60 or more` and `over £60` differ on exactly one book. Guessing between them
    produces a fully verifiable answer to a question nobody asked."""
    predicate = Executor.price_predicate(f"is there any book {phrase}?")
    assert (predicate["op"], predicate["value"]) == expected


@pytest.mark.parametrize("task", [
    "is there any expensive book in the poetry category?",   # no threshold
    "is there a book about £ in the poetry category?",       # no number
])
def test_a_price_question_we_cannot_read_produces_no_predicate(task):
    assert Executor.price_predicate(task) is None


# ---- routing --------------------------------------------------------------------

def test_a_price_question_on_the_promised_site_is_a_declared_run():
    """It was T-EXPERIMENTAL, which meant the headline rate silently excluded a case the
    dev split declares."""
    executor = Executor.__new__(Executor)
    assert executor.route(POETRY)[0] == "book_absence"


def test_a_price_question_naming_no_site_still_reaches_the_fixture():
    """The fixture's own demonstration must not be captured by the new route."""
    executor = Executor.__new__(Executor)
    assert executor.route("Is any product priced over £100?")[0] == "absence"


def test_asking_whether_anything_matches_is_not_a_request_for_the_listing():
    """Both name a category. Answering the first with a page of results answers the
    second."""
    executor = Executor.__new__(Executor)
    assert executor.route(POETRY)[0] == "book_absence"
    assert executor.route("Go to books.toscrape.com and open the Nonfiction "
                          "category, how many pages of results?")[0] == "book_category"


# ---- the verifier's side --------------------------------------------------------

def _postcondition(anchor: str = "the category listing's own results count") -> Postcondition:
    return Postcondition(
        goal="g", operation="OP-6", target_url="https://books.toscrape.com/",
        inputs={"predicate": {"field": "price_gbp", "op": ">=", "value": 60.0}},
        claims=(ClaimSpec("result_counter", "N results", Relation.COUNTER_ECHO, "counter"),
                ClaimSpec("items", "entries", Relation.LIST_ENUMERATION, "sku_list",
                          container="//x")),
        absence=AbsenceMode.B_ENUMERATION, coverage_anchor=anchor)


def _items(*prices: float) -> list[dict]:
    return [{"sku": f"book {i}", "text": "", "price_gbp": p}
            for i, p in enumerate(prices, start=1)]


def _absence(items, counter, candidate, anchor="the count", pager=None):
    extracted = {Relation.LIST_ENUMERATION: items,
                 Relation.COUNTER_ECHO: counter}
    if pager is not None:
        extracted[Relation.PAGER_POSITION] = pager
    verifier = Verifier.__new__(Verifier)
    return verifier._absence(_postcondition(anchor), extracted, [], candidate)


def test_the_results_count_is_a_coverage_anchor_in_its_own_right():
    """A category on one page has no pager. Requiring one made absence unprovable on a site
    that states its total plainly — which is the exact form A3.2 gives as an example."""
    status, failure, _ = _absence(_items(10.0, 20.0), {"count": 2}, {"matches": []})
    assert status is TerminalStatus.NO_RESULT_VERIFIED and failure is None


def test_without_any_count_absence_is_unverified_not_proven():
    status, failure, why = _absence(_items(10.0), {}, {"matches": []})
    assert status is TerminalStatus.UNVERIFIED
    assert failure is FailureClass.POSTCONDITION_UNMET
    assert "coverage anchor" in why


def test_an_incomplete_enumeration_cannot_prove_absence():
    """The site says 40, we saw 20 — the twenty we did not see are exactly where the answer
    would be."""
    status, _, why = _absence(_items(*(10.0,) * 20), {"count": 40}, {"matches": []})
    assert status is TerminalStatus.UNVERIFIED
    assert "40" in why and "20" in why


def test_a_match_found_by_the_verifier_and_by_the_run_is_a_verified_yes():
    status, failure, why = _absence(_items(10.0, 75.0), {"count": 2},
                                    {"matches": ["book 2"]})
    assert status is TerminalStatus.SUCCEEDED_VERIFIED and failure is None
    assert "book 2" in why


def test_the_run_and_the_artifact_must_agree_on_what_matched():
    """The check the old shape could not make: a run that enumerated correctly and applied
    the predicate the other way round claimed absence, and absence was all anyone checked."""
    status, failure, why = _absence(_items(10.0, 75.0), {"count": 2}, {"matches": []})
    assert status is TerminalStatus.FAILED
    assert failure is FailureClass.VERIFICATION_MISMATCH
    assert "book 2" in why


def test_a_run_that_claims_a_match_the_artifact_does_not_have_also_fails():
    """Both directions, or the check only catches under-reporting."""
    status, failure, _ = _absence(_items(10.0), {"count": 1}, {"matches": ["book 1"]})
    assert status is TerminalStatus.FAILED
    assert failure is FailureClass.VERIFICATION_MISMATCH


@pytest.mark.parametrize("op,price,matches", [(">=", 60.0, True), (">", 60.0, False),
                                              (">=", 59.99, False), (">", 60.01, True)])
def test_the_boundary_is_the_boundary(op, price, matches):
    """`at £60.00 or more` includes a book priced exactly £60.00."""
    from app.verifier import _predicate_holds

    assert _predicate_holds({"price_gbp": price},
                            {"field": "price_gbp", "op": op, "value": 60.0}) is matches

"""Replay of the two defects that shipped at M1, at the verifier layer.

The executor-level regression tests only stop those two bugs recurring. This suite asks the
question that matters: **given the artifacts those runs produced, does the verifier reject
them?** If it does not, it is not doing its job, and the place that would surface is M4
against a live site rather than here.

Both runs had the right step count, the right artifact count, a clean terminal status and a
`200` from every request. Nothing structural distinguishes them from a correct run. Each one
answered a different question than the one asked.

The artifacts are re-captures, not the originals: run storage is ephemeral, so the deploy
that shipped the fix destroyed the evidence of what it fixed. They were taken through a real
browser against the same fixture, reproducing the same two behaviours — the paginator's page-2
state for the mis-route, and a search for the greedy regex's mangled term.
"""

from __future__ import annotations

import pathlib

import pytest

from app.models import (
    FailureClass, Run, StepKind, TerminalStatus, Tier, TraceEntry, new_id,
)
from app.postcondition import (
    AbsenceMode, ClaimSpec, Postcondition, Relation, RequiredAction,
)
from app.store import Store
from app.verifier import Verifier

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
FIXTURE_HOST = "https://wf-fixture.zeabur.app"
RESULT_ROWS = '//ul[contains(@class,"results")]//li[contains(@class,"result")]'
OVERLAY_ANCHOR = ('//*[contains(normalize-space(.), "Before you continue")]'
                  '[not(.//*[contains(normalize-space(.), "Before you continue")])]')


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")


def _run(store: Store, task: str, pc: Postcondition, steps: list[TraceEntry]) -> Run:
    run = Run(id=new_id("run"), task=task, tier=Tier.EXPERIMENTAL)
    run.postcondition = pc.to_dict()
    run.postcondition_hash = pc.sha256
    run.trace = steps
    store.save_run(run)
    return run


def _step(seq: int, kind: StepKind, summary: str, selector: str = "") -> TraceEntry:
    return TraceEntry(seq=seq, kind=kind, summary=summary, ok=True,
                      detail={"selector": selector} if selector else {})


def _artifact(store: Store, run: Run, name: str, source_url: str) -> str:
    return store.put_artifact(run.id, "dom:replay",
                              (FIXTURES / name).read_bytes(),
                              source_url=source_url, media_type="text/html").id


def _overlay_postcondition() -> Postcondition:
    return Postcondition(
        goal="Read the reference code that is only reachable after dismissing the overlay",
        operation="GS-3",
        target_url=f"{FIXTURE_HOST}/gated",
        inputs={"seed": "none"},
        required_actions=(
            RequiredAction("click", "#dismiss", "the control beneath is disabled"),
            RequiredAction("click", "#reveal", "the code is not shown until revealed"),
        ),
        claims=(
            ClaimSpec("product_code", "Product code", Relation.TABLE_ROW_CELL, "code"),
            ClaimSpec("stock_on_hand", "Stock on hand", Relation.TABLE_ROW_CELL, "integer"),
            ClaimSpec("overlay_gone", "the blocking overlay", Relation.ELEMENT_ABSENT,
                      "bool", container=OVERLAY_ANCHOR),
        ),
    )


def _search_postcondition(term: str) -> Postcondition:
    return Postcondition(
        goal=f"Return the catalogue search result set for {term!r}",
        operation="GS-1",
        target_url=f"{FIXTURE_HOST}/search",
        inputs={"term": term, "seed": "none"},
        required_actions=(
            RequiredAction("fill", "#q", "the term must be typed into the form"),
            RequiredAction("click", "#do-search", "results exist only behind a POST"),
        ),
        claims=(
            ClaimSpec("result_counter", 'N results for "term"', Relation.COUNTER_ECHO,
                      "counter"),
            ClaimSpec("items", "result rows", Relation.LIST_ENUMERATION, "sku_list",
                      container=RESULT_ROWS, optional=True),
            ClaimSpec("empty_state", "No products match that search", Relation.EMPTY_STATE,
                      "bool", optional=True),
        ),
        absence=AbsenceMode.A_EMPTY_STATE,
    )


# --- Defect A: an overlay task that was routed to the paginator ---------------------

def test_replay_a_misroute_is_rejected(store):
    """"Dismiss the overlay on the gated page and read the reference code" returned
    `Page 2 of 3 · 14 products` — a correct pager reading for a question nobody asked."""
    pc = _overlay_postcondition()
    run = _run(store, "Dismiss the overlay on the gated page and read the reference code",
               pc, [_step(1, StepKind.NAVIGATE, "Navigate to /browse"),
                    _step(2, StepKind.CLICK, "Click 'Next' (1 of 1)", "#next"),
                    _step(3, StepKind.EXTRACT, "Read the visible rows on page 2")])
    art = _artifact(store, run, "replay-a-browse-page2.html", f"{FIXTURE_HOST}/browse")

    verdict = Verifier(store).verify(
        run, artifact_id=art,
        candidate={"pager": {"page": 2, "total": 3, "items": 14}})

    assert verdict.status is TerminalStatus.FAILED
    assert verdict.counts_as_success is False
    source_check = next(c for c in verdict.checks
                        if c.name == "artifact_source_matches_plan")
    assert source_check.ok is False
    assert "/browse" in source_check.detail["artifact_source_url"]
    assert "/gated" in source_check.detail["plan_target_url"]


def test_replay_a_also_fails_without_the_url_check(store):
    """Two independent barriers, not one lucky check. Even if the artifact had come from
    the page the plan targeted, `Product code` is not on it and nothing can be bound."""
    pc = _overlay_postcondition()
    # Same claims, but the plan is told to expect the page the run actually visited.
    relaxed = Postcondition(
        goal=pc.goal, operation=pc.operation, target_url=f"{FIXTURE_HOST}/browse",
        inputs=pc.inputs, required_actions=(), claims=pc.claims)
    run = _run(store, "Dismiss the overlay and read the reference code", relaxed,
               [_step(1, StepKind.EXTRACT, "Read rows")])
    art = _artifact(store, run, "replay-a-browse-page2.html", f"{FIXTURE_HOST}/browse")

    verdict = Verifier(store).verify(run, artifact_id=art,
                                     candidate={"product_code": "WF-1013",
                                                "stock_on_hand": 8, "overlay_gone": True})

    assert verdict.counts_as_success is False
    codes = next(c for c in verdict.claims if c.name == "product_code")
    assert codes.failure_class is FailureClass.LOCATOR_NOT_FOUND


# --- Defect B: a greedy regex searched for the sentence instead of the term ---------

def test_replay_b_mangled_term_is_not_a_proof_of_absence(store):
    """The dangerous one. The page really does say "0 results", the empty-state element
    really is there, and both declared actions really happened — so every check except one
    passes. Only comparing the page's echo against the frozen term catches it."""
    pc = _search_postcondition("lantern")
    run = _run(store, "Search the fixture catalogue for lantern", pc,
               [_step(1, StepKind.FILL, "Fill the search field", "#q"),
                _step(2, StepKind.CLICK, "Submit the search form", "#do-search"),
                _step(3, StepKind.EXTRACT, "Read the result counter and rows")])
    art = _artifact(store, run, "replay-b-search-mangled.html", f"{FIXTURE_HOST}/search")

    verdict = Verifier(store).verify(
        run, artifact_id=art,
        candidate={"result_counter": {"count": 0,
                                      "term": "the fixture catalogue for lant"},
                   "items": [], "empty_state": True})

    assert verdict.status is TerminalStatus.FAILED
    assert verdict.failure_class is FailureClass.VERIFICATION_MISMATCH
    assert verdict.status is not TerminalStatus.NO_RESULT_VERIFIED
    assert verdict.counts_as_success is False
    # The required actions did happen. Nothing about the run's shape is wrong.
    assert next(c for c in verdict.checks if c.name == "required_actions_present").ok


def test_replay_b_the_same_artifact_verifies_when_that_was_the_question(store):
    """The control that makes the previous test mean something.

    If the frozen question really had been the mangled string, this artifact is a valid
    proof of absence and the verifier says so. The rejection above is the binding to the
    frozen question doing work — not a verifier that refuses everything it is shown.
    """
    pc = _search_postcondition("the fixture catalogue for lant")
    run = _run(store, "Search for that exact phrase", pc,
               [_step(1, StepKind.FILL, "Fill the search field", "#q"),
                _step(2, StepKind.CLICK, "Submit the search form", "#do-search")])
    art = _artifact(store, run, "replay-b-search-mangled.html", f"{FIXTURE_HOST}/search")

    verdict = Verifier(store).verify(
        run, artifact_id=art,
        candidate={"result_counter": {"count": 0,
                                      "term": "the fixture catalogue for lant"},
                   "items": [], "empty_state": True})

    assert verdict.status is TerminalStatus.NO_RESULT_VERIFIED
    assert verdict.counts_as_success is True


def test_the_structural_checks_both_defects_passed_still_pass(store):
    """Stated as an assertion because it is the actual lesson.

    Step count, artifact count, HTTP status and terminal-status shape were all correct in
    both defective runs, which is why pre-deploy checking missed them. Anything that only
    inspects those still sees nothing wrong here.
    """
    pc = _search_postcondition("lantern")
    run = _run(store, "Search the fixture catalogue for lantern", pc,
               [_step(1, StepKind.FILL, "Fill the search field", "#q"),
                _step(2, StepKind.CLICK, "Submit the search form", "#do-search"),
                _step(3, StepKind.EXTRACT, "Read the result counter and rows")])
    art = _artifact(store, run, "replay-b-search-mangled.html", f"{FIXTURE_HOST}/search")

    assert len(run.trace) == 3
    assert all(t.ok for t in run.trace)
    assert len(store.artifacts_for_run(run.id)) == 1
    assert store.get_artifact_ref(art).state == "stored"
    # ...and the run is still wrong.
    assert Verifier(store).verify(
        run, artifact_id=art,
        candidate={"result_counter": {"count": 0,
                                      "term": "the fixture catalogue for lant"},
                   "items": [], "empty_state": True}).counts_as_success is False


# ---- OP-4: the sort that ran one click short -----------------------------------

#: The top row of the artifact a genuine one-click run produced, read cell by cell. It is
#: correct — that is the point of the case.
ONE_CLICK_TOP_ROW = {
    "Symbol": "GOOGL", "Security": "Alphabet Inc. (Class A)",
    "GICS Sector": "Communication Services",
    "GICS Sub-Industry": "Interactive Media & Services",
    "Headquarters Location": "Mountain View, California",
    "Date added": "2006-04-03", "CIK": "0001652044", "hideFounded": "1998",
}

def _op4_postcondition() -> Postcondition:
    """The same object `Executor._plan_wiki_sort` freezes, built here so the replay is
    judged by the postcondition the product actually ships."""
    from app.executor import Executor

    plan = Executor.__dict__["_plan_wiki_sort"](
        Executor.__new__(Executor),
        "On the Wikipedia list of S&P 500 companies, sort the constituents table by "
        "'GICS Sector' descending and read the top row")
    return plan.postcondition


def test_a_sort_that_stopped_one_click_short_cannot_pass_as_the_sort_that_was_asked_for(
        store):
    """The trap the spec names, replayed from the page a real one-click run produced.

    Descending order takes two clicks on a MediaWiki sortable header. One click produces a
    real table, really sorted, and a run that reads its top row reports a value that is
    genuinely there — `GOOGL` under `Communication Services`. Nothing about the run looks
    wrong: right page, right table, right column, right cell, and the reported value agrees
    with the artifact.

    The trace here shows both declared clicks, so the required-action guard is satisfied and
    cannot be what catches this. What catches it is the table's own statement of how it is
    ordered, compared against the direction frozen before browsing.
    """
    pc = _op4_postcondition()
    steps = [
        _step(1, StepKind.NAVIGATE, "Navigate to the article"),
        _step(2, StepKind.CLICK, "Click the 'GICS Sector' header (first click)"),
        _step(3, StepKind.CLICK, "Click the 'GICS Sector' header (second click)"),
        _step(4, StepKind.SNAPSHOT, "Snapshot captured"),
    ]
    run = _run(store, "sort the constituents table by GICS Sector descending", pc, steps)
    artifact = _artifact(store, run, "replay-d-op4-one-click-ascending.html",
                         "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")

    # Exactly what an honest run of the one-click page reports: it is not lying about
    # anything it saw.
    candidate = {
        "sort_state": {"column": "GICS Sector", "direction": "ascending",
                       "column_index": 2},
        "top_row": ONE_CLICK_TOP_ROW,
    }
    verdict = Verifier(store).verify(run, artifact_id=artifact, candidate=candidate)

    assert verdict.status is TerminalStatus.FAILED
    assert verdict.failure_class is FailureClass.VERIFICATION_MISMATCH
    assert not any(c.name == "sort_state" and c.ok for c in verdict.claims)
    reason = next(c.reason for c in verdict.claims if c.name == "sort_state")
    assert "descending" in reason and "ascending" in reason


def test_the_top_row_value_itself_still_verifies_against_the_artifact(store):
    """The half that makes the failure interesting: the reported cell is correct.

    If the value check had failed too, this would just be a broken run. It is the *right*
    answer to a question nobody asked, which is the failure mode the whole postcondition
    mechanism exists for, and it has to be visible as such in the claims.
    """
    pc = _op4_postcondition()
    steps = [
        _step(1, StepKind.NAVIGATE, "Navigate to the article"),
        _step(2, StepKind.CLICK, "Click the 'GICS Sector' header (first click)"),
        _step(3, StepKind.CLICK, "Click the 'GICS Sector' header (second click)"),
    ]
    run = _run(store, "sort the constituents table by GICS Sector descending", pc, steps)
    artifact = _artifact(store, run, "replay-d-op4-one-click-ascending.html",
                         "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    verdict = Verifier(store).verify(run, artifact_id=artifact, candidate={
        "sort_state": {"column": "GICS Sector", "direction": "ascending",
                       "column_index": 2},
        "top_row": ONE_CLICK_TOP_ROW,
    })

    by_name = {c.name: c for c in verdict.claims}
    assert by_name["top_row"].ok
    assert not by_name["sort_state"].ok


def test_the_same_page_check_is_not_fooled_by_percent_encoding():
    """A guard that fails closed can be wrong for years without anyone noticing.

    A plan freezes the escaped URL it navigated to; the browser reports back whatever
    spelling it settled on. One page written two ways was being treated as two pages, which
    failed correct runs — and because the failure is a refusal, it looked like caution.
    """
    from app.verifier import _same_page

    escaped = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    decoded = "https://en.wikipedia.org/wiki/List_of_S&P_500_companies"
    assert _same_page(decoded, escaped)
    assert _same_page(escaped, decoded)
    # ...and still says no to a genuinely different page.
    assert not _same_page("https://en.wikipedia.org/wiki/S%26P_500", escaped)

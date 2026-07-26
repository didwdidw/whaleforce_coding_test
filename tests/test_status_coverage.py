"""The failure classes that do not need a browser, and the ledger that tracks them.

Every value in the two closed sets is declared with the milestone at which it becomes
producible. A value that is due and has never been produced is an unreachable code path —
which is exactly how M1's hard gate appeared to pass without ever having run. So the ledger
distinguishes *observed from a run* from *observed from the suite*, and refuses to let
"there is a branch for it" stand in for "it happened".
"""

from __future__ import annotations

import pathlib

import pytest

from app.coverage import FAILURE_DUE, STATUS_DUE, CoverageLedger
from app.models import (
    FailureClass, Run, StepKind, TerminalStatus, Tier, TraceEntry, new_id,
)
from app.postcondition import (
    AbsenceMode, ClaimSpec, Postcondition, Relation, RequiredAction,
)
from app.store import Store
from app.verifier import Verifier

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
HOST = "https://wf-fixture.zeabur.app"
OVERLAY_ANCHOR = ('//*[contains(normalize-space(.), "Before you continue")]'
                  '[not(.//*[contains(normalize-space(.), "Before you continue")])]')


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")


def _run_with(store: Store, pc: Postcondition, artifact: str, source_url: str,
              trace: list[TraceEntry]) -> tuple[Run, str]:
    run = Run(id=new_id("run"), task="replay", tier=Tier.EXPERIMENTAL)
    run.postcondition, run.postcondition_hash = pc.to_dict(), pc.sha256
    run.trace = trace
    store.save_run(run)
    art = store.put_artifact(run.id, "dom:replay", (FIXTURES / artifact).read_bytes(),
                             source_url=source_url, media_type="text/html")
    return run, art.id


# --- postcondition_unmet: the state transition that never happened ------------------

def test_an_undismissed_overlay_is_postcondition_unmet_not_a_missing_locator(store):
    """The run says it dismissed the overlay. The artifact still contains it. That is not
    "we could not find something" — it is the declared end state not being true."""
    pc = Postcondition(
        goal="Read the reference code", operation="GS-3", target_url=f"{HOST}/gated",
        required_actions=(),
        claims=(ClaimSpec("overlay_gone", "the blocking overlay", Relation.ELEMENT_ABSENT,
                          "bool", container=OVERLAY_ANCHOR),))
    run, art = _run_with(store, pc, "replay-c-gated-overlay-present.html",
                         f"{HOST}/gated",
                         [TraceEntry(seq=1, kind=StepKind.CLICK,
                                     summary="Dismiss the blocking overlay",
                                     detail={"selector": "#dismiss"})])

    verdict = Verifier(store).verify(run, artifact_id=art,
                                     candidate={"overlay_gone": True})
    assert verdict.status is TerminalStatus.FAILED
    assert verdict.failure_class is FailureClass.POSTCONDITION_UNMET
    assert not verdict.counts_as_success


# --- unverified: absence without a proof of absence --------------------------------

def test_absence_without_a_declared_proof_mode_is_unverified(store):
    """Amendment 3's rule, at the only place it can be enforced. The page really does say
    zero results — and without a declared proof mode that is still only "we did not find
    it", which is never `no_result_verified`."""
    pc = Postcondition(
        goal="Search", operation="GS-1", target_url=f"{HOST}/search",
        inputs={"term": "the fixture catalogue for lant"},
        claims=(ClaimSpec("result_counter", 'N results for "term"',
                          Relation.COUNTER_ECHO, "counter"),),
        absence=AbsenceMode.NONE)
    run, art = _run_with(store, pc, "replay-b-search-mangled.html", f"{HOST}/search", [])

    verdict = Verifier(store).verify(
        run, artifact_id=art,
        candidate={"result_counter": {"count": 0,
                                      "term": "the fixture catalogue for lant"}})
    assert verdict.status is TerminalStatus.UNVERIFIED
    assert verdict.failure_class is FailureClass.POSTCONDITION_UNMET
    assert not verdict.counts_as_success


def test_mode_b_without_a_coverage_anchor_cannot_conclude_absence(store):
    """A3.2 in one assertion: enumeration alone is not coverage."""
    pc = Postcondition(
        goal="Anything over £100?", operation="GS-4", target_url=f"{HOST}/browse",
        inputs={"predicate": {"field": "price_gbp", "op": ">", "value": 100.0}},
        claims=(ClaimSpec("items", "every row", Relation.LIST_ENUMERATION, "sku_list",
                          container='//div[@id="pages"]//li[contains(@class,"result")]'),),
        absence=AbsenceMode.B_ENUMERATION,
        coverage_anchor="")
    run, art = _run_with(store, pc, "replay-a-browse-page2.html", f"{HOST}/browse", [])
    skus = [f"WF-10{n:02d}" for n in range(1, 15)]

    verdict = Verifier(store).verify(run, artifact_id=art, candidate={"items": skus})
    assert verdict.status is TerminalStatus.UNVERIFIED
    assert verdict.failure_class is FailureClass.POSTCONDITION_UNMET
    assert "coverage anchor" in verdict.explanation


def test_a_tampered_postcondition_fails_before_anything_is_checked(store):
    """S-4.12. If the object verification runs against is not the frozen one, the bar could
    have moved during the run, and that is a failure regardless of the answer."""
    pc = Postcondition(goal="g", operation="GS-1", target_url=f"{HOST}/search")
    run, art = _run_with(store, pc, "replay-b-search-mangled.html", f"{HOST}/search", [])
    run.postcondition = {**run.postcondition, "goal": "something easier"}

    verdict = Verifier(store).verify(run, artifact_id=art, candidate={})
    assert verdict.status is TerminalStatus.FAILED
    assert verdict.failure_class is FailureClass.VERIFICATION_MISMATCH
    assert next(c for c in verdict.checks if c.name == "postcondition_frozen").ok is False


def test_an_expired_artifact_fails_loudly_rather_than_verifying_nothing(store):
    """An evidence bundle whose bytes have aged out must not resolve to a pass. The row
    survives expiry by design (A9.7.2); the verification does not."""
    pc = Postcondition(goal="g", operation="GS-1", target_url=f"{HOST}/search")
    run, art = _run_with(store, pc, "replay-b-search-mangled.html", f"{HOST}/search", [])
    store.enforce_retention(retention_days=0)

    verdict = Verifier(store).verify(run, artifact_id=art, candidate={})
    assert verdict.status is TerminalStatus.FAILED
    assert verdict.failure_class is FailureClass.INTERNAL_ERROR
    assert store.get_artifact_ref(art).state == "expired"
    assert store.get_artifact_ref(art).sha256          # the reference never dangles


# --- the ledger ------------------------------------------------------------------

def test_the_ledger_keeps_the_first_observation_not_the_latest(store):
    ledger = CoverageLedger(store)
    ledger.record(status=TerminalStatus.FAILED, failure=FailureClass.TIMEOUT,
                  run_id="run_first", task="a")
    ledger.record(status=TerminalStatus.FAILED, failure=FailureClass.TIMEOUT,
                  run_id="run_second", task="b")
    row = next(r for r in store.status_coverage() if r["failure_class"] == "timeout")
    assert row["first_run_id"] == "run_first"
    assert row["n"] == 2


def test_an_unobserved_due_value_is_reported_as_overdue(store):
    report = CoverageLedger(store, "M2").report()
    assert report["gate_passes"] is False
    assert "succeeded_verified" in report["overdue"]


def test_values_not_due_until_later_are_not_counted_against_m2(store):
    report = CoverageLedger(store, "M2").report()
    later = {r["value"]: r for r in report["failure_class"] if not r["due_now"]}
    assert set(later) == {"provider_quota", "provider_error", "token_budget_exhausted",
                          "context_budget_exceeded", "injection_detected"}
    assert not any(r["overdue"] for r in later.values())


def test_every_declared_value_has_a_milestone(store):
    """A value in the closed set with no declared milestone is one nobody has decided how
    to reach, which is the state that hides an unreachable path."""
    assert set(STATUS_DUE) == set(TerminalStatus)
    assert set(FAILURE_DUE) == set(FailureClass)

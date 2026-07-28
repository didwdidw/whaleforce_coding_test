"""Amendment 11: persistence, retention, and the two defect classes promoted to rules.

The two rules are the reason this file is not just about volumes. A11.7 says a verification
that passes because there was nothing to check is a defect; A11.8 says an explicitly-set
falsy value is not an absent one. Both started as single bugs found while writing M2 tests,
and both are the kind of bug that produces a clean-looking result rather than an error —
which is why the class matters more than the instance.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from app import config
from app.config import ConfigError, _bool, _int, _path, _str
from app.coverage import CoverageLedger
from app.models import FailureClass, Run, TerminalStatus, Tier, new_id
from app.postcondition import ClaimSpec, Postcondition, Relation
from app.store import Store, StoreUnavailable
from app.verifier import Verifier

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
HOST = "https://wf-fixture.zeabur.app"


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")


def _run_with(store: Store, pc: Postcondition, artifact: str = "replay-b-search-mangled.html",
              source_url: str = f"{HOST}/search", pinned: bool = False):
    run = Run(id=new_id("run"), task="t", tier=Tier.EXPERIMENTAL)
    run.postcondition, run.postcondition_hash = pc.to_dict(), pc.sha256
    store.save_run(run)
    art = store.put_artifact(run.id, "dom:replay", (FIXTURES / artifact).read_bytes(),
                             source_url=source_url, media_type="text/html", pinned=pinned)
    return run, art.id


# --- A11.7: vacuous verification fails closed --------------------------------------

def test_a_scope_the_verifier_cannot_check_is_reported_unevaluated_not_passed(tmp_path):
    """The vacuity defect, caught reappearing inside the fix for another one (A26 review).

    Splitting the exact-page gate left a fall-through that appended
    `artifact_source_matches_plan: True` for every other scope without comparing anything —
    §5.4's defect 1, a constraint recorded as satisfied that was never evaluated, under a
    name that says it was. A check this file cannot evaluate says so."""
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    pc = Postcondition(
        goal="read a labelled field", operation="OP-7",
        target_url="https://books.toscrape.com/x.html",
        inputs={"url_scope": "a scope from the future"},
        claims=(ClaimSpec("upc", "UPC", Relation.TABLE_ROW_CELL, "code"),))
    run = Run(id=new_id("run"), task="t", tier=Tier.DECLARED)
    run.postcondition, run.postcondition_hash = pc.to_dict(), pc.sha256
    store.save_run(run)
    artifact = store.put_artifact(
        run.id, "dom:step-1", b"<table><tr><th>UPC</th><td>a897fe39b1053632</td></tr></table>",
        source_url="https://books.toscrape.com/x.html", media_type="text/html")

    verdict = Verifier(store).verify(run, artifact_id=artifact.id,
                                     candidate={"upc": "a897fe39b1053632",
                                                "upc_anchor": "UPC"})

    check = next(c for c in verdict.checks if c.name == "artifact_source_matches_plan")
    assert check.ok is None, "an unevaluated constraint must not read as a satisfied one"
    assert check.evaluated is False
    # ...and naming it is not enough. Continuing would let a run reach success with no
    # artifact-source gate having run at all, which is fail-open on a hard gate.
    assert verdict.status is TerminalStatus.UNVERIFIED
    assert verdict.failure_class is FailureClass.POSTCONDITION_UNMET
    assert verdict.counts_as_success is False
    assert "not a scope this verifier knows" in check.detail["not_evaluated_because"]
    named = [row["check"] for row in verdict.evidence_summary["unevaluated_checks"]]
    assert "artifact_source_matches_plan" in named, (
        "and it is named where a reader looks for the safeguards that did not run")


def test_a_postcondition_with_no_claims_fails_rather_than_succeeding(store):
    """The original instance. It reported `succeeded_verified` for having done nothing."""
    run, art = _run_with(store, Postcondition(goal="g", operation="GS-x",
                                              target_url=f"{HOST}/search"))
    verdict = Verifier(store).verify(run, artifact_id=art, candidate={})
    assert verdict.status is TerminalStatus.FAILED
    assert verdict.failure_class is FailureClass.POSTCONDITION_UNMET
    assert verdict.counts_as_success is False
    assert "nothing to verify" in verdict.explanation


def test_all_optional_claims_cannot_reach_success(store):
    """A claim set that is entirely optional is an empty claim set wearing a hat: the run
    could pass with not one value confirmed."""
    pc = Postcondition(
        goal="g", operation="GS-1", target_url=f"{HOST}/search",
        inputs={"term": "the fixture catalogue for lant"},
        claims=(ClaimSpec("result_counter", 'N results for "term"', Relation.COUNTER_ECHO,
                          "counter", optional=True),))
    run, art = _run_with(store, pc)
    verdict = Verifier(store).verify(
        run, artifact_id=art,
        candidate={"result_counter": {"count": 0,
                                      "term": "the fixture catalogue for lant"}})
    assert verdict.status is TerminalStatus.FAILED
    assert verdict.counts_as_success is False
    assert "optional" in verdict.explanation


def test_zero_anchors_resolved_is_a_failed_verification_not_an_unverified_answer(store):
    """Nothing was examined, so nothing was verified — and "nothing failed" is not a pass.

    This is narrower than `unverified`, which stays for the case where an anchor *did*
    resolve and the claim still could not be established (absence without a proof mode).
    """
    pc = Postcondition(
        goal="g", operation="GS-3", target_url=f"{HOST}/search",
        claims=(ClaimSpec("product_code", "Product code", Relation.TABLE_ROW_CELL, "code"),
                ClaimSpec("stock_on_hand", "Stock on hand", Relation.TABLE_ROW_CELL,
                          "integer")))
    run, art = _run_with(store, pc)          # a search results page: neither label exists
    verdict = Verifier(store).verify(run, artifact_id=art,
                                     candidate={"product_code": "WF-1013",
                                                "stock_on_hand": 8})
    assert verdict.status is TerminalStatus.FAILED
    assert verdict.failure_class is FailureClass.LOCATOR_NOT_FOUND
    assert all(not c.ok for c in verdict.claims)


def test_an_empty_coverage_ledger_is_not_a_passing_gate(store):
    report = CoverageLedger(store, "M2").report()
    assert report["gate_passes"] is False


def test_the_fixture_selftest_cannot_pass_by_comparing_nothing():
    from fixture import catalogue

    assert catalogue.selftest()["ok"] is True
    # ...and it is the comparison that passes, not the absence of one.
    original = catalogue.ITEMS
    try:
        catalogue.ITEMS = ()
        result = catalogue.selftest()
    finally:
        catalogue.ITEMS = original
    assert result["ok"] is False
    assert any("proves nothing" in f["reason"] for f in result["failures"])


# --- A11.8: an explicit falsy value is not an absent one ----------------------------

def test_an_explicit_zero_is_not_replaced_by_the_default(monkeypatch):
    monkeypatch.setenv("WF_TEST_INT", "0")
    assert _int("WF_TEST_INT", 14) == 0


def test_an_explicit_false_is_not_replaced_by_a_true_default(monkeypatch):
    monkeypatch.setenv("WF_TEST_BOOL", "false")
    assert _bool("WF_TEST_BOOL", True) is False
    monkeypatch.setenv("WF_TEST_BOOL", "0")
    assert _bool("WF_TEST_BOOL", True) is False


def test_an_unset_variable_is_the_only_thing_that_takes_the_default(monkeypatch):
    monkeypatch.delenv("WF_TEST_INT", raising=False)
    assert _int("WF_TEST_INT", 14) == 14


def test_an_unreadable_value_stops_the_process_rather_than_defaulting(monkeypatch):
    """Silently falling back would mean an operator who set something wrong gets the
    default and no signal — the same family as a safety flag resolving to permissive."""
    monkeypatch.setenv("WF_TEST_INT", "fourteen")
    with pytest.raises(ConfigError) as exc:
        _int("WF_TEST_INT", 14)
    assert "WF_TEST_INT" in str(exc.value)

    monkeypatch.setenv("WF_TEST_BOOL", "maybe")
    with pytest.raises(ConfigError):
        _bool("WF_TEST_BOOL", False)

    monkeypatch.setenv("WF_TEST_PATH", "   ")
    with pytest.raises(ConfigError):
        _path("WF_TEST_PATH", "/data/task1")


def test_an_explicit_empty_string_is_a_set_value(monkeypatch):
    monkeypatch.setenv("WF_TEST_STR", "")
    assert _str("WF_TEST_STR", "fallback") == ""


def test_provenance_records_where_each_value_came_from(monkeypatch):
    monkeypatch.setenv("WF_TEST_PROV", "7")
    _int("WF_TEST_PROV", 1)
    monkeypatch.delenv("WF_TEST_OTHER", raising=False)
    _int("WF_TEST_OTHER", 1)
    prov = config.config_provenance()
    assert prov["from_environment"]["WF_TEST_PROV"] == "7"
    assert "WF_TEST_OTHER" in prov["defaulted"]


def test_retention_days_zero_means_now_not_fourteen_days(store):
    """The instance that produced the rule."""
    run, art = _run_with(store, Postcondition(goal="g", operation="x", target_url=HOST))
    result = store.enforce_retention(retention_days=0)
    assert result["expired_by_age"] == 1
    assert store.get_artifact_ref(art).state == "expired"


# --- A11.3: pinned evidence is never evicted ---------------------------------------

def test_a_pinned_artifact_survives_an_age_sweep_that_expires_everything_else(store):
    _, pinned = _run_with(store, Postcondition(goal="g", operation="x", target_url=HOST),
                          pinned=True)
    _, ordinary = _run_with(store, Postcondition(goal="g", operation="x", target_url=HOST))

    store.enforce_retention(retention_days=0)

    assert store.get_artifact_ref(pinned).state == "stored"
    assert store.get_artifact_ref(ordinary).state == "expired"


def test_a_pinned_artifact_survives_disk_pressure(store):
    """A grader arriving two weeks after deployment must not find that the first screen is
    three expired links (A11.3)."""
    _, pinned = _run_with(store, Postcondition(goal="g", operation="x", target_url=HOST),
                          pinned=True)
    _, ordinary = _run_with(store, Postcondition(goal="g", operation="x", target_url=HOST))

    result = store.enforce_retention(retention_days=3650, max_mib=0)

    assert store.get_artifact_ref(pinned).state == "stored"
    assert store.get_artifact_ref(ordinary).state == "expired"
    assert result["expired_by_size"] == 1
    assert result["over_ceiling"] is True      # the remainder is pinned, and it says so


# --- A11.4: expiry is a dated record, not an error ---------------------------------

def test_expiry_keeps_every_piece_of_metadata_and_a_date(store):
    run, art = _run_with(store, Postcondition(goal="g", operation="x", target_url=HOST))
    before = store.get_artifact_ref(art).to_dict()

    store.enforce_retention(retention_days=0)
    after = store.get_artifact_ref(art).to_dict()

    assert after["state"] == "expired"
    assert after["available"] is False
    assert after["expired_on"] is not None
    for field in ("artifact_id", "source_url", "retrieved_at", "sha256", "length",
                  "retrieved_on"):
        assert after[field] == before[field], f"{field} did not survive expiry"
    assert store.read_artifact(art) is None


def test_every_eviction_is_recorded(store):
    _run_with(store, Postcondition(goal="g", operation="x", target_url=HOST))
    store.enforce_retention(retention_days=0)
    events = store.retention_events()
    assert events and events[0]["reason"] == "age"
    assert events[0]["artifacts"] == 1
    assert events[0]["bytes"] > 0


# --- A11.5 / A11.6: the store reports its own state --------------------------------

def test_the_write_probe_actually_writes(store):
    probe = store.probe()
    assert probe["writable"] is True
    assert not (store.artifact_dir / ".write-probe").exists()   # and cleans up after itself


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only directory")
def test_an_unwritable_store_refuses_to_start_rather_than_falling_back(tmp_path):
    """A path-existence check passes here. That is the point of probing with a write."""
    data = tmp_path / "readonly"
    (data / "artifacts").mkdir(parents=True)
    data.chmod(0o500)
    (data / "artifacts").chmod(0o500)
    try:
        with pytest.raises(StoreUnavailable) as exc:
            Store(data / "runs.sqlite3", data / "artifacts")
        assert "not usable" in str(exc.value)
        assert "DATA_DIR" in str(exc.value)
    finally:
        data.chmod(0o700)
        (data / "artifacts").chmod(0o700)


def test_a_writable_directory_that_is_not_a_mount_is_refused_in_production(tmp_path,
                                                                          monkeypatch):
    """The failure a write probe alone cannot see.

    The image creates `/data`, so with no volume attached the directory exists and is
    writable. Everything works, nothing looks wrong, and every artifact disappears on the
    next deploy — which is the condition the volume was mounted to fix.
    """
    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "true")
    with pytest.raises(StoreUnavailable) as exc:
        Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    assert "not a mounted volume" in str(exc.value)
    # ...and the same directory is fine once the requirement does not apply.
    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    assert Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts").probe()["writable"]


def test_storage_status_reports_the_ceiling_before_evidence_starts_disappearing(store):
    _run_with(store, Postcondition(goal="g", operation="x", target_url=HOST))
    status = store.storage_status()
    assert status["writable"] is True
    # Honest in a test run: a tmp_path is not a mount, so persistence is reported as false
    # rather than assumed from the fact that writing worked.
    assert status["persistent"] is False
    assert status["mount_required"] is False
    assert status["artifacts_stored"] == 1
    assert 0 <= status["fraction_of_ceiling"] < 1
    assert status["approaching_ceiling"] is False
    assert status["data_dir"].endswith("artifacts")

"""Scored splits do not run on the public path, and a degraded run says so in its file.

A18.10: validation and test splits need the billing credential (A9.6), and the container
serving anonymous traffic must never hold it (A12.2). Those two rules make the public URL
the wrong endpoint for an eval split — not merely the expensive one. The workload that does
hold the key is not reachable from outside the host, so it drives the harness itself and
leaves the result on the shared volume.

A18.7: a result produced while the system was impaired carries that inside its own
provenance block, because a filename gets separated from the number it qualifies.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.server import app
from eval import scored_workload
from eval.harness import degradation


# ---- A18.7: the qualifier travels inside the file --------------------------------

CLEAN_META = {"planner_available": True, "credentials": {"policy": "scored"}}


def _case(name: str, **kwargs) -> dict:
    base = {"case": name, "failure_class": None, "suite_error": False,
            "timed_out_waiting": False}
    return {**base, **kwargs}


def test_a_clean_run_carries_no_degradation_block():
    assert degradation(CLEAN_META, [_case("DEV-01")], "dev") is None


def test_quota_refusals_make_the_file_not_a_capability_measurement():
    block = degradation(CLEAN_META,
                        [_case("DEV-01", failure_class="provider_quota"),
                         _case("DEV-02", failure_class="provider_quota")],
                        "dev")
    assert block["not_a_capability_measurement"] is True
    assert "DEV-01" in block["reasons"][0] and "DEV-02" in block["reasons"][0]


@pytest.mark.parametrize("results,expected", [
    ([_case("DEV-03", suite_error=True)], "precondition"),
    ([_case("DEV-04", timed_out_waiting=True)], "still running"),
])
def test_other_impairments_are_named_individually(results, expected):
    block = degradation(CLEAN_META, results, "dev")
    assert any(expected in reason for reason in block["reasons"])


def test_an_unavailable_planner_degrades_the_whole_split():
    block = degradation({**CLEAN_META, "planner_available": False}, [_case("DEV-01")], "dev")
    assert "planner was unavailable" in " ".join(block["reasons"])


def test_a_held_out_split_on_the_wrong_credential_is_degraded():
    """The free tier can die halfway through a split that cannot be re-run (A9.6)."""
    meta = {"planner_available": True, "credentials": {"policy": "public_demo"}}
    block = degradation(meta, [_case("V-01")], "test")
    assert "'scored'" in " ".join(block["reasons"])
    # The same credential on a visible split is a choice, not an impairment.
    assert degradation(meta, [_case("DEV-01")], "dev") is None


# ---- A18.10: the results come out through the shared volume ----------------------

@pytest.fixture()
def results_dir(tmp_path, monkeypatch) -> pathlib.Path:
    directory = tmp_path / "eval-results"
    directory.mkdir()
    monkeypatch.setattr(type(settings), "eval_results_dir",
                        property(lambda self: directory))
    return directory


def test_the_public_service_serves_what_the_scored_workload_wrote(results_dir):
    report = {"provenance": {"split": "dev", "git_sha": "abc123def456",
                             "finished_at": "2026-07-28T00:00:00Z"},
              "aggregate": {"headline_declared": {"cases": 11, "passed": 10}}}
    (results_dir / "dev-deploy-abc123def456-r1.json").write_text(json.dumps(report))

    client = TestClient(app)
    listing = client.get("/api/eval-results").json()
    assert [f["file"] for f in listing["files"]] == ["dev-deploy-abc123def456-r1.json"]
    assert listing["files"][0]["split"] == "dev"
    assert listing["files"][0]["degraded"] is False
    fetched = client.get("/api/eval-results/dev-deploy-abc123def456-r1.json").json()
    assert fetched["aggregate"]["headline_declared"]["passed"] == 10


def test_the_listing_shows_that_a_file_is_degraded_without_opening_it(results_dir):
    (results_dir / "dev-deploy-x-r1.json").write_text(json.dumps(
        {"provenance": {"split": "dev", "degraded": {"not_a_capability_measurement": True}}}))
    assert TestClient(app).get("/api/eval-results").json()["files"][0]["degraded"] is True


@pytest.mark.parametrize("name", ["../runs.sqlite3", "..%2Fruns.sqlite3", "secret",
                                  "a/b.json", ".env.json"])
def test_no_name_can_leave_the_results_directory(results_dir, name):
    """The route reads a directory, not a path. Containment is the same requirement the
    artifact store carries (A12.7); it is stated once per surface that reads files."""
    assert TestClient(app).get(f"/api/eval-results/{name}").status_code in (400, 404)


# ---- a round is priced before the first case, not discovered at the fourteenth ----

def _spend(today: float, cumulative: float | None = None) -> dict:
    return {"today_usd": today, "cumulative_usd": cumulative if cumulative is not None
            else today}


def test_a_round_is_priced_from_its_own_case_count():
    plan = scored_workload.forecast(["dev", "experimental"], _spend(0.0))
    assert plan["cases_priced"] == sum(n for n in plan["cases_per_split"].values() if n)
    assert plan["expected_usd"] == pytest.approx(
        plan["cases_priced"] * plan["usd_per_run_measured"] * plan["safety_factor"], rel=1e-6)
    # The tail is priced too: every run spending its whole token budget.
    assert plan["worst_case_usd"] > plan["expected_usd"]


def test_a_split_whose_cases_are_not_in_the_image_is_not_priced_as_zero():
    """A held-out split is mounted at score time. Counting it as nothing would forecast a
    round of 15 cases and then run 40."""
    plan = scored_workload.forecast(["dev", "validation"], _spend(0.0))
    assert plan["cases_not_in_this_image"] == ["validation"]


def test_the_round_is_refused_before_the_first_case_when_it_cannot_be_afforded():
    """The daily ceiling stops a run mid-call, which turns one round into a half-blocked
    file whose name is already taken. Refusing the whole round at case zero costs nothing."""
    ceiling = scored_workload.settings.provider.spend_ceiling_usd_per_day
    plan = scored_workload.forecast(["dev", "experimental"], _spend(ceiling - 0.001))
    assert plan["affordable"] is False
    with pytest.raises(SystemExit) as exit_info:
        scored_workload.check_affordable(plan)
    assert "case one costs nothing" in str(exit_info.value)


def test_an_affordable_round_with_an_unaffordable_tail_warns_and_proceeds(capsys):
    """Refusing on the worst case would refuse almost every round: the tail is ~20x the
    measured cost. It is said out loud instead, with what happens if it lands."""
    plan = scored_workload.forecast(["dev", "experimental"], _spend(0.75))
    assert plan["affordable"] is True and plan["worst_case_affordable"] is False
    scored_workload.check_affordable(plan)
    assert "-degraded" in capsys.readouterr().out


def test_a_degraded_result_does_not_take_the_round_s_name(results_dir):
    clean = scored_workload.result_path("dev", "abc123", "1")
    degraded = scored_workload.result_path("dev", "abc123", "1", degraded=True)
    assert clean != degraded
    assert degraded.name.endswith("-degraded.json")


# ---- the workload refuses to be the wrong workload -------------------------------

def _settings_with(**provider_fields):
    return dataclasses.replace(
        settings, provider=dataclasses.replace(settings.provider, **provider_fields))


def test_it_refuses_to_score_on_a_credential_policy_that_is_not_scored(monkeypatch):
    monkeypatch.setattr(scored_workload, "settings",
                        _settings_with(credential_policy="public_demo"))
    with pytest.raises(SystemExit) as exit_info:
        scored_workload.preflight()
    assert "CREDENTIAL_POLICY" in str(exit_info.value)


def test_it_refuses_to_score_with_no_billing_credential_present(monkeypatch, tmp_path):
    monkeypatch.setattr(scored_workload, "settings",
                        _settings_with(credential_policy="scored", key_dir=tmp_path))
    with pytest.raises(SystemExit) as exit_info:
        scored_workload.preflight()
    assert "billing credential" in str(exit_info.value)


def test_the_server_it_drives_is_loopback_only(monkeypatch):
    """Not "unpublished" — bound to loopback, so the platform's private network cannot
    reach it either. The property A12.3 asks for is about the socket, not the domain."""
    recorded = {}

    class _Popen:
        def __init__(self, argv, **kwargs):
            recorded["argv"] = argv

    monkeypatch.setattr(scored_workload.subprocess, "Popen", _Popen)
    scored_workload.start_server(8080, pathlib.Path("/tmp/scored-test.log"))
    assert "--host" in recorded["argv"]
    assert recorded["argv"][recorded["argv"].index("--host") + 1] == "127.0.0.1"


def _staged(monkeypatch, calls, report=None):
    """`run` with the server and the split stubbed, so only its own decisions are tested."""
    monkeypatch.setattr(scored_workload, "preflight", lambda: None)
    monkeypatch.setattr(scored_workload, "start_server",
                        lambda port, log: type("P", (), {
                            "send_signal": lambda self, s: None,
                            "wait": lambda self, timeout=None: None})())
    monkeypatch.setattr(scored_workload, "wait_until_healthy",
                        lambda base, deadline: {"ok": True, "git_sha": "abc123",
                                                "provider_spend": {"today_usd": 0.0,
                                                                   "cumulative_usd": 0.0}})
    monkeypatch.setattr(scored_workload, "run_split",
                        lambda *a, **k: calls.append(a) or (
                            report or {"aggregate": {}, "provenance": {}}))


def test_a_dry_run_submits_nothing_and_writes_nothing(results_dir, monkeypatch, capsys):
    """The operator's first start of a scoring service should not be the one that spends,
    and a dry run that works by accident of a missing case file is not a mechanism."""
    calls = []
    _staged(monkeypatch, calls)
    scored_workload.run(["dev", "experimental"], port=8080, round_id="1", force=False,
                        deadline=1.0, startup_deadline=1.0, idle=False, dry_run=True)

    assert calls == []
    assert list(results_dir.iterdir()) == []
    out = capsys.readouterr().out
    assert "dry run" in out
    # The forecast is printed either way: the point of the dry run is to see the price.
    assert "expected_usd" in out


def test_a_degraded_round_leaves_the_clean_name_free(results_dir, monkeypatch):
    """Otherwise the next start sees a result "exists" for the round, skips the split, and
    the number that survives is the broken one."""
    degraded = {"aggregate": {}, "provenance": {"degraded": {
        "not_a_capability_measurement": True, "reasons": ["quota"]}}}
    _staged(monkeypatch, [], report=degraded)
    scored_workload.run(["dev"], port=8080, round_id="1", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)

    assert not scored_workload.result_path("dev", "abc123", "1").exists()
    assert scored_workload.result_path("dev", "abc123", "1", degraded=True).exists()


def test_a_restart_does_not_re_run_a_split_that_already_has_a_result(results_dir,
                                                                    monkeypatch):
    """A platform restart is free for the platform and not for us: re-running a scored
    split spends billed quota and overwrites the result it was spent on."""
    out = scored_workload.result_path("dev", "abc123", "1")
    out.write_text("{}")

    calls = []
    monkeypatch.setattr(scored_workload, "preflight", lambda: None)
    monkeypatch.setattr(scored_workload, "start_server",
                        lambda port, log: type("P", (), {
                            "send_signal": lambda self, s: None,
                            "wait": lambda self, timeout=None: None})())
    monkeypatch.setattr(scored_workload, "wait_until_healthy",
                        lambda base, deadline: {"ok": True, "git_sha": "abc123"})
    monkeypatch.setattr(scored_workload, "run_split",
                        lambda *a, **k: calls.append(a) or {"aggregate": {}})

    scored_workload.run(["dev"], port=8080, round_id="1", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)
    assert calls == [], "a split with an existing result file must not be re-run"

    scored_workload.run(["dev"], port=8080, round_id="2", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)
    assert len(calls) == 1, "a new round must run"

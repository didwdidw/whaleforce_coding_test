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
    written = next(f for f in listing["files"]
                   if f["file"] == "dev-deploy-abc123def456-r1.json")
    assert written["split"] == "dev"
    assert written["degraded"] is False
    assert written["source"] == "volume"
    fetched = client.get("/api/eval-results/dev-deploy-abc123def456-r1.json").json()
    assert fetched["aggregate"]["headline_declared"]["passed"] == 10


def test_a_committed_result_is_served_without_any_volume(results_dir):
    """A21.3. The scored workload has a volume of its own that no other service can read,
    so a round reaches the public surface by being committed and shipped in the image."""
    listing = TestClient(app).get("/api/eval-results").json()
    from_repo = [f for f in listing["files"] if f["source"] == "repository"]
    assert from_repo, "the committed results in eval/results/ must be served"
    name = from_repo[0]["file"]
    assert TestClient(app).get(f"/api/eval-results/{name}").status_code == 200


def test_a_committed_result_wins_over_a_copy_left_on_the_volume(results_dir):
    """A committed file has been reviewed; the volume holds whatever the last writer left."""
    name = "dev-local-427cd96.json"
    (results_dir / name).write_text(json.dumps({"provenance": {"split": "tampered"}}))

    listing = TestClient(app).get("/api/eval-results").json()
    entries = [f for f in listing["files"] if f["file"] == name]
    assert len(entries) == 1 and entries[0]["source"] == "repository"
    assert entries[0]["split"] != "tampered"


def test_the_listing_shows_that_a_file_is_degraded_without_opening_it(results_dir):
    (results_dir / "dev-deploy-x-r1.json").write_text(json.dumps(
        {"provenance": {"split": "dev", "degraded": {"not_a_capability_measurement": True}}}))
    listing = TestClient(app).get("/api/eval-results").json()["files"]
    assert next(f for f in listing if f["file"] == "dev-deploy-x-r1.json")["degraded"] is True


@pytest.mark.parametrize("name", ["../runs.sqlite3", "..%2Fruns.sqlite3", "secret",
                                  "a/b.json", ".env.json"])
def test_no_name_can_leave_the_results_directory(results_dir, name):
    """The route reads a directory, not a path. Containment is the same requirement the
    artifact store carries (A12.7); it is stated once per surface that reads files."""
    assert TestClient(app).get(f"/api/eval-results/{name}").status_code in (400, 404)


# ---- a round is priced before the first case, not discovered at the fourteenth ----

def _spend(today: float, cumulative: float | None = None) -> dict:
    """Billed dollars. The forecast prices a paid round, and A23.1 removed the combined
    figure it used to read — a total that also counted free-tier calls."""
    return {"today_billed_usd": today,
            "cumulative_billed_usd": cumulative if cumulative is not None else today}


@pytest.fixture(autouse=True)
def _scored_policy(monkeypatch):
    """Forecasting only ever happens in the scored workload, and its daily ceiling is its
    share of the system total (A22.2). Under the default `public_demo` policy this module
    would price rounds against the reservation held for a process that cannot spend."""
    monkeypatch.setattr(scored_workload, "settings",
                        dataclasses.replace(settings, provider=dataclasses.replace(
                            settings.provider, credential_policy="scored")))


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
    ceiling = scored_workload.settings.provider.spend_ceiling_usd_per_day
    plan = scored_workload.forecast(["dev", "experimental"], _spend(ceiling - 0.25))
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
                                                "provider_spend": _spend(0.0)})
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
                        lambda base, deadline: {"ok": True, "git_sha": "abc123",
                                                "provider_spend": _spend(0.0)})
    monkeypatch.setattr(scored_workload, "run_split",
                        lambda *a, **k: calls.append(a) or {"aggregate": {}})

    scored_workload.run(["dev"], port=8080, round_id="1", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)
    assert calls == [], "a split with an existing result file must not be re-run"

    scored_workload.run(["dev"], port=8080, round_id="2", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)
    assert len(calls) == 1, "a new round must run"


def test_a_redeploy_cannot_start_a_fresh_paid_round(results_dir, monkeypatch):
    """The commit is in the result's *name*, and this platform redeploys on every push. A
    sha-keyed guard would hold for restarts, which are free, and fail for a push, which is
    the case that spends: a new sha means a new filename means a whole round again."""
    calls = []
    _staged(monkeypatch, calls)
    scored_workload.run(["dev"], port=8080, round_id="1", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)
    assert len(calls) == 1

    monkeypatch.setattr(scored_workload, "wait_until_healthy",
                        lambda base, deadline: {"ok": True, "git_sha": "def456",
                                                "provider_spend": _spend(0.0)})
    scored_workload.run(["dev"], port=8080, round_id="1", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)
    assert len(calls) == 1, "the same round number on a new commit is still the same round"


def test_a_refusal_holds_the_container_instead_of_crash_looping(monkeypatch, capsys):
    """Live: the service came up, refused, exited non-zero, and the platform restarted it on
    a backoff. All the operator saw was `BackOff: Back-off restarting failed container` —
    a message about restarting that never names the cause, with the reason scrolled away."""
    monkeypatch.setattr(scored_workload, "run",
                        lambda *a, **kw: scored_workload._refuse("the volume is not mounted"))
    held = []
    monkeypatch.setattr(scored_workload, "hold", lambda reason, **kw: held.append(reason) or 0)

    assert scored_workload.main(["--splits", "dev"]) == 0
    assert "the volume is not mounted" in held[0]


def test_an_unexpected_crash_also_holds_with_its_traceback(monkeypatch):
    """A traceback in a crash loop is a traceback nobody reads."""
    def boom(*a, **kw):
        raise RuntimeError("chrome would not start")

    monkeypatch.setattr(scored_workload, "run", boom)
    held = []
    monkeypatch.setattr(scored_workload, "hold", lambda reason, **kw: held.append(reason) or 0)

    assert scored_workload.main(["--splits", "dev"]) == 0
    assert "chrome would not start" in held[0]
    assert "CRASHED" in held[0]


def test_holding_is_a_container_behaviour_and_not_a_cli_one(monkeypatch):
    """Run from a terminal with --no-idle, a refusal is still a non-zero exit: there is no
    backoff loop to defend against and a shell wants the status code."""
    monkeypatch.setattr(scored_workload, "run",
                        lambda *a, **kw: scored_workload._refuse("no billing credential"))
    monkeypatch.setattr(scored_workload, "hold",
                        lambda reason, **kw: pytest.fail("must not hold with --no-idle"))

    with pytest.raises(SystemExit) as exit_info:
        scored_workload.main(["--splits", "dev", "--no-idle"])
    assert "no billing credential" in str(exit_info.value)


def test_the_held_reason_is_repeated_so_a_log_window_shows_it(monkeypatch, capsys):
    """The operator opens the log at an arbitrary moment. A reason printed once at start-up
    is not there when they look."""
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(scored_workload.time, "sleep", fake_sleep)
    with pytest.raises(KeyboardInterrupt):
        scored_workload.hold("REFUSING: no billing credential", interval=900.0)

    err = capsys.readouterr().err
    assert err.count("no billing credential") == 2  # once at the refusal, once per interval
    assert "would be restarted" in err


def test_the_store_check_creates_its_own_directory_on_a_fresh_volume(tmp_path):
    """Live: preflight demanded `task1/`, which the *application's* store creates — and
    preflight runs before the server. It passed only because the workload was sharing a
    volume the app had already written to. Given a volume of its own it refused forever.
    A precondition satisfied by another process's side effect is not a precondition."""
    mount = tmp_path / "data"
    mount.mkdir()
    data_dir = mount / "task1"

    scored_workload.check_writable_store(data_dir)
    assert data_dir.is_dir()
    assert not (data_dir / ".writable").exists(), "the write probe must clean up after itself"


def test_the_store_check_refuses_when_the_mount_point_is_absent(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        scored_workload.check_writable_store(tmp_path / "absent" / "task1")
    assert "wrong with the image" in str(exit_info.value)


def test_the_store_check_refuses_a_directory_it_cannot_write(tmp_path):
    """A round whose database is not persisted is a round that gets paid for twice."""
    mount = tmp_path / "data"
    mount.mkdir(mode=0o555)
    try:
        with pytest.raises(SystemExit) as exit_info:
            scored_workload.check_writable_store(mount / "task1")
        assert "not writable" in str(exit_info.value)
    finally:
        mount.chmod(0o755)


# ---- A22.3/A22.4: one declared ceiling, divided, and visible from either end -------

def test_the_two_ceilings_come_from_one_declaration_and_add_up_to_the_promise():
    """A22.1-A22.3. Two ceilings set independently drift, and neither process can read the
    other's ledger, so the drift is invisible — which is how USD 1/day quietly became 2."""
    from app import config

    total = config.SYSTEM_SPEND_CEILING_USD_PER_DAY
    # The public demo runs under exactly one of its two policies at a time (A27.1), so the
    # split adds up per alternative rather than across the dict — summing all of it would
    # count the same process twice and read as a raise.
    for demo_policy in config.PUBLIC_DEMO_POLICIES:
        processes = [p for p in config.DEPLOYED_CEILING_SHARE
                     if p not in config.PUBLIC_DEMO_POLICIES] + [demo_policy]
        assert sum(config.DEPLOYED_CEILING_SHARE[p] for p in processes) == pytest.approx(1.0)
        per_process = [
            dataclasses.replace(settings.provider, credential_policy=p
                                ).spend_ceiling_usd_per_day
            for p in processes
        ]
        assert sum(per_process) == pytest.approx(total)
    assert total == pytest.approx(2.0)


def test_the_old_per_service_ceiling_variable_is_refused_rather_than_ignored(monkeypatch):
    """Leaving it silently inert would let an operator set it, see no error, and believe a
    ceiling was applied — the same shape as the check that reported on a coincidence."""
    import importlib

    from app import config

    monkeypatch.setenv("PROVIDER_SPEND_CEILING_USD_PER_DAY", "5.00")
    with pytest.raises(RuntimeError) as raised:
        importlib.reload(config)
    assert "no longer does anything" in str(raised.value)
    monkeypatch.delenv("PROVIDER_SPEND_CEILING_USD_PER_DAY")
    importlib.reload(config)


def test_a_health_endpoint_shows_the_system_total_not_only_its_own_share():
    """A22.4: a promise a reader has to reconstruct by adding two services is not visible."""
    from app.provider import Provider

    state = Provider(ledger=None).spend_state()
    assert state["system_ceiling_usd_per_day"] == pytest.approx(2.0)
    assert state["ceiling_usd_per_day"] < state["system_ceiling_usd_per_day"]
    assert state["system_split"]["scored"] + state["system_split"]["public_demo"] == 1.0
    assert state["credential_policy"]


# ---- A20.3: the round is locked to the build it started on ------------------------

def test_a_round_whose_deployment_changed_underneath_it_is_degraded(results_dir, monkeypatch):
    """A20.2 says nobody pushes during a round. A20.3 is what catches the day somebody
    does: cases before and after the swap measured different systems."""
    monkeypatch.setattr(scored_workload, "_healthz_sha", lambda base: "def456789abc")
    reason = scored_workload.check_deployment_unchanged("http://test", "abc123456def")
    assert "changed under the round" in reason
    assert "abc123456def" in reason and "def456789abc" in reason


def test_an_unreadable_commit_mid_round_is_also_a_finding(monkeypatch):
    """Not being able to show the build was stable is not the same as showing it was."""
    def unreadable(base):
        raise OSError("connection refused")

    monkeypatch.setattr(scored_workload, "_healthz_sha", unreadable)
    reason = scored_workload.check_deployment_unchanged("http://test", "abc123456def")
    assert "could not be re-read" in reason


def test_a_stable_deployment_produces_no_finding(monkeypatch):
    monkeypatch.setattr(scored_workload, "_healthz_sha", lambda base: "abc123456def")
    assert scored_workload.check_deployment_unchanged("http://test", "abc123456def") is None


def test_a_split_that_died_mid_round_is_not_silently_re_run(results_dir, monkeypatch):
    """A container killed part-way through a paid split leaves no result, so the round
    guard would decide it was never scored and pay for it again."""
    calls = []
    _staged(monkeypatch, calls)
    scored_workload.inflight_marker("dev", "1").parent.mkdir(parents=True, exist_ok=True)
    scored_workload.mark_round_started("dev", "1", "abc123")

    with pytest.raises(SystemExit) as exit_info:
        scored_workload.run(["dev"], port=8080, round_id="1", force=False, deadline=1.0,
                            startup_deadline=1.0, idle=False)
    assert "started and never finished" in str(exit_info.value)
    assert calls == [], "a round that may already have been paid for is not re-run quietly"


def test_another_rounds_leftover_marker_does_not_block_this_one(results_dir, monkeypatch):
    """The disposition an operator would otherwise have to decide at the dashboard.

    r2's experimental split was cut in half and its marker is still on the volume. If the
    refusal keyed on the split alone, starting r3 would hold — and somebody would delete a
    scoring file by hand, minutes before a paid round, to get past it. It keys on the round
    as well, so r3 simply runs and the record of r2's unfinished split stays where it is."""
    calls = []
    _staged(monkeypatch, calls)
    scored_workload.inflight_marker("dev", "2").parent.mkdir(parents=True, exist_ok=True)
    scored_workload.mark_round_started("dev", "2", "abc123")

    scored_workload.run(["dev"], port=8080, round_id="3", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)

    assert len(calls) == 1, "r3 is not held by r2's marker"
    assert scored_workload.inflight_marker("dev", "2").exists(), (
        "and r2's record of a paid, unfinished split is not tidied away by r3")


def test_a_finished_split_leaves_no_inflight_marker(results_dir, monkeypatch):
    calls = []
    _staged(monkeypatch, calls)
    scored_workload.run(["dev"], port=8080, round_id="1", force=False, deadline=1.0,
                        startup_deadline=1.0, idle=False)
    assert len(calls) == 1
    assert not scored_workload.inflight_marker("dev", "1").exists()


# ---- mounting a held-out split (S-10.4, S-10.6) -----------------------------------

def test_a_held_out_split_is_taken_from_where_the_operator_mounted_it(monkeypatch, tmp_path):
    """Held-out case content is never in the image, so the path comes from the operator."""
    mounted = tmp_path / "test-set.md"
    mounted.write_text("# held out\n", encoding="utf-8")
    monkeypatch.setenv("EVAL_CASES_TEST", str(mounted))

    assert scored_workload.case_file("test") == mounted
    # A visible split is unaffected and still comes from the image.
    assert scored_workload.case_file("dev").name == "dev-set.md"


def test_the_committed_hashes_are_read_from_the_manifest_not_duplicated():
    """The manifest is the published claim; a second copy is a second thing to keep in step."""
    hashes = scored_workload.holdout_hashes()
    assert set(hashes) == {"validation", "test"}
    assert all(len(h) == 64 for h in hashes.values())


def test_a_mounted_split_that_is_not_the_committed_one_is_refused_before_spending(tmp_path):
    """A held-out split is scored once and that run is the reported score. A wrong, edited or
    truncated file produces a perfectly plausible number for a split nobody can identify —
    and the mount point is where that goes wrong, because the file arrives by hand."""
    wrong = tmp_path / "test-set.md"
    wrong.write_text("# not the delivered file\n", encoding="utf-8")

    problem = scored_workload.holdout_hash_mismatch("test", wrong)

    assert "eval/holdout-manifest.md commits" in problem
    assert "scored once" in problem


def test_a_split_with_no_committed_hash_is_not_gated(tmp_path):
    """Dev and experimental are visible and change with the code; gating them on a hash
    would refuse every round after an edit to a case."""
    visible = tmp_path / "dev-set.md"
    visible.write_text("# anything\n", encoding="utf-8")
    assert scored_workload.holdout_hash_mismatch("dev", visible) == ""

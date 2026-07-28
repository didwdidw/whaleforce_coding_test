"""Measuring the service under load, and the two ways the measurement lied first (A14.2).

Both defects here were found by running the tool rather than by reading it, and both had the
same shape: a number that looked plausible and was about something other than what it was
labelled. The first was in the product — a run refused at the door stayed in state `queued`
forever, so anything waiting for it waited forever. The second was in the tool — a refusal
carries a `run_id` in its body, so counting `run_id`s counted every refusal as an admission
and the deployment appeared to have unlimited capacity.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.queue import AdmissionRefused
from app.models import FailureClass
from eval.loadtest import measure_saturation


# ---- the product side -----------------------------------------------------------

class _Request:
    """Enough of a request for the submit handler: it reads one cookie."""

    cookies: dict[str, str] = {}


@pytest.fixture(scope="module")
def refusal() -> dict:
    """One submission to a deployment whose queue is full.

    The handler is called directly rather than through a client, because `app.server.state`
    is a module-level singleton whose store is closed by the first test that runs a
    lifespan, and this needs no lifespan at all.
    """
    from app import server
    from app.coverage import CoverageLedger
    from app.store import Store

    server.state.store = Store()
    server.state.coverage = CoverageLedger(server.state.store)

    def full(run):
        raise AdmissionRefused("The queue is full.", FailureClass.QUEUE_FULL,
                               retry_after=5)

    admit = server.state.queue.admit
    server.state.queue.admit = full
    try:
        response = asyncio.run(server.submit(_Request(), task="Search for lantern"))
    finally:
        server.state.queue.admit = admit
    body = json.loads(response.body)
    run = server.state.store.load_run(body["run_id"])
    return {"status": response.status_code, "body": body, "run": run.to_dict()}


def test_a_run_refused_at_the_door_is_finished_not_queued(refusal):
    """It has a terminal status and a finish time; leaving the state at `queued` made the
    API describe a finished run as still waiting, and left the run page polling for a state
    that would never arrive."""
    assert refusal["status"] == 429
    run = refusal["run"]
    assert run["state"] == "done"
    assert run["terminal_status"] == "blocked"
    assert run["failure_class"] == "queue_full"
    assert run["finished_at"] is not None


def test_the_refused_run_reads_terminal_on_every_surface(refusal):
    """A-52. The API, the run page and the health endpoint report the same lifecycle
    position at the same instant, because all three read the recorded state rather than
    deciding for themselves (A17.7)."""
    from app import server
    from app.models import RunState

    run = server.state.store.load_run(refusal["body"]["run_id"])

    # The API.
    assert run.to_dict()["state"] == "done"
    # The page: the run template asks the same property, and the polling block it guards is
    # not rendered — so nothing is left waiting for a state that will never arrive.
    assert run.effective_state is RunState.DONE
    # The health endpoint: the queue never took it, so it is in no in-flight count.
    snapshot = server.state.queue.snapshot().to_dict()
    assert server.state.queue.position_of(run.id) is None
    assert snapshot["running"] == 0


def test_a_lifecycle_field_left_behind_cannot_make_a_finished_run_look_queued():
    """The derivation, asserted directly. A run carrying a terminal status is terminal on
    every surface whatever the lifecycle field says — the two got out of step once, and
    each surface deciding for itself is what let it stay that way."""
    from app.models import Run, RunState, TerminalStatus, Tier

    run = Run(id="run_x", task="t", tier=Tier.DECLARED, state=RunState.QUEUED)
    assert run.effective_state is RunState.QUEUED

    run.terminal_status = TerminalStatus.BLOCKED
    assert run.effective_state is RunState.DONE
    assert run.to_dict()["state"] == "done"


def test_the_elapsed_time_stops_when_the_run_does():
    """A number that keeps growing after the run ended is recomputed at render time, and a
    recomputed number is a fabricated one (A17.7)."""
    import time

    from app.models import BudgetUse

    budget = BudgetUse(started_at=time.time() - 10)
    running = budget.to_dict()["elapsed_seconds"]
    budget.ended_at = budget.started_at + 2.0
    assert budget.to_dict()["elapsed_seconds"] == 2.0
    assert running > 2.0
    time.sleep(0.05)
    assert budget.to_dict()["elapsed_seconds"] == 2.0


def test_a_refusal_still_carries_a_run_id_which_is_why_counting_them_was_wrong(refusal):
    """Kept as a test because the tool's bug depended on this being true, and it should stay
    true: the refusal is a real, inspectable run."""
    assert refusal["body"]["run_id"]
    assert refusal["body"]["failure_class"] == "queue_full"


# ---- the measurement side -------------------------------------------------------

def test_saturation_counts_admissions_by_status_code_not_by_body(monkeypatch):
    """Two of six admitted, four refused. Reading `run_id` from the body instead reported
    six admitted and a system that never saturates."""
    import eval.loadtest as loadtest

    answers = iter([{"http": 202, "run_id": "run_1"}, {"http": 202, "run_id": "run_2"}]
                   + [{"http": 429, "run_id": f"run_{i}", "failure_class": "queue_full"}
                      for i in range(3, 7)])
    monkeypatch.setattr(loadtest, "_submit", lambda base, task, **kw: next(answers))
    monkeypatch.setattr(loadtest, "_drain", lambda *a, **kw: [])

    report = measure_saturation("http://test", [6], deadline_seconds=1.0)
    assert report["sweep"] == [{"burst": 6, "admitted": 2, "refused": 4,
                                "refused_as": ["queue_full"]}]
    assert report["saturation_point"]["value"] == 6
    assert "no model call" in report["saturation_point"]["measured_under"]


def test_a_sweep_that_is_never_refused_says_so_rather_than_reporting_a_number(monkeypatch):
    """"Saturation point: 6" when six was simply the largest burst tried would be a claim
    about the deployment made out of the tool's own arguments."""
    import eval.loadtest as loadtest

    monkeypatch.setattr(loadtest, "_submit",
                        lambda base, task, **kw: {"http": 202, "run_id": "run_1"})
    monkeypatch.setattr(loadtest, "_drain", lambda *a, **kw: [])

    report = measure_saturation("http://test", [2, 4], deadline_seconds=1.0)
    assert report["saturation_point"]["value"] is None
    assert "above 4" in report["reading"]


def test_the_projection_is_labelled_as_arithmetic_not_as_an_observation():
    """A14.2 asks for measurement. The model-driven figure is not one, and the field that
    carries it has to say so wherever it is read."""
    from eval.loadtest import project_model_driven

    projection = project_model_driven(2, 30.0)
    assert projection["projected_runs_per_minute"]["value"] == 4.0
    # The qualifier travels with the number, not in a footnote beside it (A17.13).
    assert "a projection, not an observation" in (
        projection["projected_runs_per_minute"]["measured_under"])
    assert "not observed" in projection["basis"]


# ---- deploy to first successful request (A17.14) ---------------------------------

def _sequence(monkeypatch, health, runs=None):
    """Drive `watch` off a scripted sequence of /healthz answers."""
    import eval.coldstart as coldstart

    answers = iter(health)
    last = health[-1]
    monkeypatch.setattr(coldstart.time, "sleep", lambda s: None)
    monkeypatch.setattr(coldstart, "_get", lambda base, path, timeout=5.0: (
        next(answers, last) if path == "/healthz"
        else (200, (runs or {"state": "done"}))))
    monkeypatch.setattr(coldstart, "_post",
                        lambda base, task, timeout=30.0: (202, {"run_id": "run_1"}))
    return coldstart


def test_a_stale_reply_from_the_old_container_does_not_end_the_measurement(monkeypatch):
    """The build is identified by its commit, not by the service answering. A deployment
    that is still routing to the previous container answers instantly and would report a
    cold start of zero."""
    coldstart = _sequence(monkeypatch, [
        (200, {"git_sha": "old", "ok": True}),
        (200, {"git_sha": "old", "ok": True}),
        (None, {}),
        (200, {"git_sha": "new", "ok": True}),
    ])

    report = coldstart.watch("http://test", t0=None, deadline_seconds=30, poll_seconds=0)

    assert report["baseline_git_sha"] == "old"
    assert report["new_git_sha"] == "new"
    assert report["seconds_to_first_response"] is not None
    assert report["seconds_to_first_successful_task"] is not None


def test_answering_is_not_the_same_as_working(monkeypatch):
    """A service that serves /healthz and cannot yet finish a task is not up in the sense
    anybody cares about, so the measurement carries on to a real run."""
    coldstart = _sequence(monkeypatch,
                          [(200, {"git_sha": "old", "ok": True}),
                           (200, {"git_sha": "new", "ok": True})],
                          runs={"state": "done"})

    report = coldstart.watch("http://test", t0=None, deadline_seconds=30, poll_seconds=0)

    assert report["probe_run_id"] == "run_1"
    assert (report["seconds_to_first_successful_task"]
            >= report["seconds_to_first_response"])


def test_the_fallback_t0_is_labelled_as_a_lower_bound(monkeypatch):
    """Without a deploy timestamp the clock starts at the last response from the old
    build, which is at or after the button press. Reporting that as *the* cold start
    without saying so would be a number quietly rounded in our favour."""
    coldstart = _sequence(monkeypatch, [(200, {"git_sha": "old", "ok": True}),
                                        (200, {"git_sha": "new", "ok": True})])

    report = coldstart.watch("http://test", t0=None, deadline_seconds=30, poll_seconds=0)
    assert "lower bound" in report["t0_origin"]

    coldstart = _sequence(monkeypatch, [(200, {"git_sha": "old", "ok": True}),
                                        (200, {"git_sha": "new", "ok": True})])
    stamped = coldstart.watch("http://test", t0=1_700_000_000.0, deadline_seconds=30,
                              poll_seconds=0)
    assert stamped["t0_origin"] == "the operator's deploy timestamp"


def test_no_new_build_is_reported_as_no_measurement(monkeypatch):
    """A deadline that expires without a new commit answering has produced nothing, and
    saying so is the only honest output."""
    coldstart = _sequence(monkeypatch, [(200, {"git_sha": "old", "ok": True})] * 50)

    report = coldstart.watch("http://test", t0=None, deadline_seconds=0.01, poll_seconds=0)
    assert "error" in report
    assert "seconds_to_first_response" not in report


# ---- a startup answer about a rate limit is not a permanent answer -----------------

def test_a_quota_refusal_at_startup_is_re_checked_once_its_window_has_passed(monkeypatch):
    """One boot-time call landing inside a rate limit made the deployment report
    `planner unavailable` for the life of the container. A missing credential is not
    re-checked, because that one does not fix itself."""
    import time

    from app import server
    from app.config import settings

    server.state.planner_status = {"available": False, "failure_class": "provider_quota",
                                   "retryable": True, "checked_at": time.time()}
    monkeypatch.setattr(server, "_check_planner",
                        lambda: server.state.planner_status.update(
                            {"available": True, "retryable": False}))

    inside = server._planner_status()
    assert inside["available"] is False
    assert inside["retry_in_seconds"] > 0

    server.state.planner_status["checked_at"] = (
        time.time() - settings.provider.quota_cooldown_seconds - 1)
    assert server._planner_status()["available"] is True


def test_a_missing_credential_is_not_re_checked_on_every_health_probe(monkeypatch):
    from app import server

    server.state.planner_status = {"available": False, "failure_class": "provider_error",
                                   "reason": "no credential"}
    monkeypatch.setattr(server, "_check_planner",
                        lambda: pytest.fail("re-validated a missing credential"))
    assert server._planner_status()["available"] is False

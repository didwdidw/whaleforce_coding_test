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
    assert report["saturation_point"] == 6


def test_a_sweep_that_is_never_refused_says_so_rather_than_reporting_a_number(monkeypatch):
    """"Saturation point: 6" when six was simply the largest burst tried would be a claim
    about the deployment made out of the tool's own arguments."""
    import eval.loadtest as loadtest

    monkeypatch.setattr(loadtest, "_submit",
                        lambda base, task, **kw: {"http": 202, "run_id": "run_1"})
    monkeypatch.setattr(loadtest, "_drain", lambda *a, **kw: [])

    report = measure_saturation("http://test", [2, 4], deadline_seconds=1.0)
    assert report["saturation_point"] is None
    assert "above 4" in report["reading"]


def test_the_projection_is_labelled_as_arithmetic_not_as_an_observation():
    """A14.2 asks for measurement. The model-driven figure is not one, and the field that
    carries it has to say so wherever it is read."""
    from eval.loadtest import project_model_driven

    projection = project_model_driven(2, 30.0)
    assert projection["projected_runs_per_minute"] == 4.0
    assert "not observed" in projection["basis"]

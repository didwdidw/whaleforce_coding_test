"""The run detail page renders, for every outcome a run can end in.

This file exists because it did not. `/runs/{id}` is the page every claim about
inspectability points at — the trace, the artifacts, the verdict, the reason a refusal was
a refusal — and it was the one surface with no test that so much as fetched it. A commit
that added a template block reading `build.locator_memory` did not add `build` to that
route's context; Jinja2's default `Undefined` prints and iterates and is falsey without
complaint, and raises only on attribute access, so the page 500'd from that commit onward
while every other page stayed green. It survived three scored rounds.

So the assertion here is deliberately shallow and deliberately total: **for each terminal
status, and for a run still in flight, fetch the page and require 200.** Depth was never
the problem. Nobody had ever asked for the page.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import (
    FailureClass, Run, RunState, StepKind, TerminalStatus, Tier, TraceEntry, new_id,
)
from app.store import Store


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """A store of this module's own. `app.server.state` is a module-level singleton whose
    store an earlier lifespan may already have closed."""
    from app import server

    previous = server.state.store
    server.state.store = Store(tmp_path_factory.mktemp("runs") / "runs.sqlite3",
                               tmp_path_factory.mktemp("artifacts"))
    # No lifespan: this needs the routes, not a browser.
    yield TestClient(server.app, raise_server_exceptions=False)
    server.state.store = previous


def _saved(client, **fields) -> str:
    from app import server

    run = Run(id=new_id("run"), task="Look up the price of WF-1013", tier=Tier.EXPERIMENTAL,
              **fields)
    server.state.store.save_run(run)
    return run.id


@pytest.mark.parametrize("status", list(TerminalStatus), ids=lambda s: s.value)
def test_the_detail_page_renders_for_every_terminal_status(client, status):
    run_id = _saved(client, state=RunState.DONE, terminal_status=status,
                    failure_class=None if status is TerminalStatus.SUCCEEDED_VERIFIED
                    else FailureClass.POSTCONDITION_UNMET,
                    explanation="Rendered by the test suite.")
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200, response.text[-2000:]
    assert run_id in response.text


def test_the_detail_page_renders_for_a_run_that_has_not_finished(client):
    """The in-flight branch mounts the progress stream, and is a different template path
    from every finished run above."""
    run_id = _saved(client, state=RunState.RUNNING)
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200, response.text[-2000:]
    assert "EventSource" in response.text


def test_the_detail_page_renders_a_run_carrying_trace_artifacts_and_a_verdict(client):
    """The panels that only appear when there is something to show."""
    from app import server

    run_id = _saved(client, state=RunState.DONE,
                    terminal_status=TerminalStatus.SUCCEEDED_VERIFIED)
    run = server.state.store.load_run(run_id)
    run.trace = [
        TraceEntry(seq=0, kind=StepKind.NAVIGATE, summary="navigate",
                   detail={"url": "https://wf-fixture.zeabur.app/product/WF-1013"}),
        TraceEntry(seq=1, kind=StepKind.EXTRACT, summary="extract", detail={"verdict": {
            "status": "verified",
            "checks": [{"name": "artifact_source_is_accounted_for_by_the_trace", "ok": True,
                        "detail": {}}],
            "evidence_summary": {"note": "rendered by the test suite"},
        }}),
    ]
    run.claims = [{"field": "price", "value": "39.90"}]
    server.state.store.save_run(run)
    for entry in run.trace:
        server.state.store.save_trace_entry(run_id, entry)
    server.state.store.put_artifact(run_id, "dom", b"<html></html>",
                                    source_url="https://wf-fixture.zeabur.app/product/WF-1013",
                                    media_type="text/html")

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200, response.text[-2000:]
    assert "artifact_source_is_accounted_for_by_the_trace" in response.text


def test_an_unknown_run_is_a_404_and_not_a_crash(client):
    assert client.get("/runs/run_deadbeefdead").status_code == 404

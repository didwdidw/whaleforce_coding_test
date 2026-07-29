"""The homepage's sentences about itself, asserted against what it renders.

Two of these were found by an independent reviewer operating the deployed site. The page
promised a `pre-executed` badge and a capture date on rows that carried neither, and it
offered `/api/runs` as the escape hatch that justifies de-duplicating the table while that
route answered 405. Both survived a review that was looking for exactly this, because the
only tests near them asserted the paragraph text — and a paragraph asserting itself is the
defect, not the check.

So nothing here asserts prose. Each test builds a store, renders the page, and compares
what came out against the values the code derived from that store.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.models import Run, RunState, TerminalStatus, Tier, new_id
from app.store import Store

PINNED_TASK = "Browse the fixture catalogue"


@pytest.fixture()
def client(tmp_path):
    from app import server

    previous = server.state.store
    server.state.store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    yield TestClient(server.app, raise_server_exceptions=False)
    server.state.store = previous


def _run(client, task: str, *, pre_executed: bool = False) -> Run:
    from app import server

    run = Run(id=new_id("run"), task=task, tier=Tier.DECLARED, state=RunState.DONE,
              terminal_status=TerminalStatus.SUCCEEDED_VERIFIED, pre_executed=pre_executed)
    server.state.store.save_run(run)
    return run


def _busy_deployment(client) -> Run:
    """A pinned demonstration, then enough later traffic to push it out of any window of
    recent runs — including a live run of the same task, which is what evicted it before."""
    from app import server

    pinned = _run(client, PINNED_TASK, pre_executed=True)
    server.state.store.put_artifact(pinned.id, "dom", b"<html>pinned</html>",
                                    source_url="https://wf-fixture.zeabur.app/catalogue",
                                    media_type="text/html", pinned=True)
    _run(client, PINNED_TASK)
    for i in range(70):
        _run(client, f"Search the fixture catalogue for lantern {i}")
    return pinned


def test_the_promised_badge_and_capture_date_are_on_a_row_that_is_really_there(client):
    """The badge is promised unconditionally, so it has to render on a deployment that has
    served real traffic — not only on an empty one."""
    from app import server

    pinned = _busy_deployment(client)
    page = client.get("/").text

    row = re.search(rf"<tr[^>]*>(?:(?!</tr>).)*{pinned.id}(?:(?!</tr>).)*</tr>", page, re.S)
    assert row, "the pinned demonstration is not on the page at all"
    assert "pre-executed" in row.group(0), "the row is there and the promised badge is not"

    captured = server.state.store.artifacts_for_run(pinned.id)[0].retrieved_on
    assert f"evidence captured {captured}" in row.group(0), (
        "the date is read off the artifact the run stored, so this compares the page "
        "against that value rather than against the sentence promising it")


def test_a_live_run_of_the_same_task_does_not_evict_the_demonstration(client):
    """They are two different claims about one task: what the build did at startup, and
    what it does now. De-duplication is for the measurement probe, not for these."""
    pinned = _busy_deployment(client)
    page = client.get("/").text

    assert pinned.id in page
    assert len(re.findall(r">pre-executed<", page)) >= 1
    # And the de-duplication it coexists with still works.
    assert page.count("Search the fixture catalogue for lantern 0") <= 1


def test_the_full_list_the_page_points_at_answers_and_is_longer_than_the_table(client):
    """The paragraph's justification for de-duplicating is that nothing is hidden. That is
    only true while this endpoint exists, which for several deployments it did not."""
    _busy_deployment(client)

    listed = client.get("/api/runs")
    assert listed.status_code == 200, listed.text[:400]
    body = listed.json()

    page = client.get("/").text
    on_page = {m for m in re.findall(r"run_[0-9a-f]+", page)}
    ids = [r["id"] for r in body["runs"]]

    assert body["total"] == len(ids) or body["truncated"]
    assert len(ids) > len(on_page), (
        "the endpoint that justifies hiding rows has to show more than the table does")
    assert on_page <= set(ids), "a row on the page is missing from the full list"
    assert ids == sorted(ids, key=lambda i: [r["created_at"] for r in body["runs"]
                                             if r["id"] == i][0], reverse=True)


def test_the_listing_carries_the_fields_a_reader_needs_to_pick_a_run(client):
    from app import server

    pinned = _busy_deployment(client)
    body = client.get("/api/runs").json()
    row = next(r for r in body["runs"] if r["id"] == pinned.id)
    run = server.state.store.load_run(pinned.id)

    assert row["task"] == run.task
    assert row["tier"] == run.tier.value
    assert row["terminal_status"] == run.terminal_status.value
    assert row["counts_as_success"] is run.counts_as_success
    assert row["pre_executed"] is True
    assert row["steps"] == run.budget.steps
    assert row["detail_url"] == f"/runs/{run.id}"
    assert client.get(row["detail_url"]).status_code == 200


def test_the_listing_says_when_it_is_showing_a_page_rather_than_everything(client):
    """Truncating silently would make the same promise false again, one deployment later."""
    _busy_deployment(client)
    body = client.get("/api/runs?limit=5").json()

    assert len(body["runs"]) == 5
    assert body["truncated"] is True
    assert body["next_offset"] == 5
    assert body["total"] > 5

    rest = client.get(f"/api/runs?limit=5&offset={body['next_offset']}").json()
    assert rest["runs"][0]["id"] not in {r["id"] for r in body["runs"]}

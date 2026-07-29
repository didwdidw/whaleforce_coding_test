"""What the run pages say about the demonstrations and about a run in flight.

Round two of the same review found the same shape of defect again: sentences that were true
when they were written and describe something else now. The demonstrations were seeded once
and pinned — across an unknown number of restarts and at least one older verifier — while
the page said they ran at startup; three of four example buttons no longer matched the
demonstration rows they claimed to be; and a run in flight showed two step counts that
disagreed with nothing marking either as live.

Same rule as last round: build the state, render the page, compare against what the code
derived. Nothing here asserts a sentence.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.demo import CHIPS, PRE_EXECUTED
from app.models import Run, RunState, StepKind, TerminalStatus, Tier, TraceEntry, new_id
from app.store import Store


def _flat(text: str) -> str:
    """Prose wraps in the template; the claim is the same claim on one line or three."""
    return re.sub(r"\s+", " ", text)


@pytest.fixture()
def client(tmp_path):
    from app import server

    fresh = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    # The deployment has one store and every reader holds that one. Swapping the app's
    # reference alone leaves the coverage ledger, the provider ledger and the locator
    # memory on a handle another test may already have closed — and `/healthz` reads all
    # of them.
    holders = [(server.state, "store"),
               (server.state.coverage, "_store"),
               (server.state.provider, "ledger"),
               (server.state.executor, "_store"),
               (server.state.executor._coverage, "_store"),
               (server.state.executor._verifier, "_store"),
               (server.state.executor._locator_memory, "_store")]
    previous = [(obj, name, getattr(obj, name)) for obj, name in holders]
    for obj, name in holders:
        setattr(obj, name, fresh)
    yield TestClient(server.app, raise_server_exceptions=False)
    for obj, name, value in previous:
        setattr(obj, name, value)


def _save(task: str, **kw) -> Run:
    from app import server

    run = Run(id=new_id("run"), task=task, tier=Tier.DECLARED, state=RunState.DONE,
              terminal_status=TerminalStatus.SUCCEEDED_VERIFIED, **kw)
    server.state.store.save_run(run)
    return run


# ---- the demonstrations are this build's, and the buttons re-run them ---------------

def test_demonstrations_from_another_build_are_re_seeded_not_kept():
    """The store outlives the container, so "seed if nothing is pinned" pinned the first
    build ever to boot against this volume — and kept it."""
    from app import server

    current = [Run(id=new_id("run"), task=t, tier=Tier.DECLARED, pre_executed=True,
                   session_id="pre-executed:abc123abc123") for t in PRE_EXECUTED]

    assert server._stale_demonstrations(current, "pre-executed:abc123abc123") == ""
    assert server._stale_demonstrations(current, "pre-executed:def456def456")
    assert server._stale_demonstrations([], "pre-executed:abc123abc123")
    assert server._stale_demonstrations(current[:-1], "pre-executed:abc123abc123"), (
        "a demo list that has changed leaves rows nothing on the page can reproduce")


def test_withdrawing_a_demonstration_keeps_the_run(client, tmp_path):
    """The claim is withdrawn, not the evidence: the run stays in the table and on the
    listing endpoint, it just stops presenting itself as what this build does."""
    from app import server

    pinned = _save("Search the fixture catalogue for lantern", pre_executed=True,
                   session_id="pre-executed:old")

    assert server.state.store.unpin_pre_executed() == 1
    assert server.state.store.recent_runs(limit=5, pre_executed=True) == []
    assert server.state.store.load_run(pinned.id) is not None
    assert pinned.id in {r["id"] for r in client.get("/api/runs").json()["runs"]}


def test_the_page_names_the_build_its_pinned_rows_came_from(client):
    """Read off the rows, not off the process: the two differ exactly when it matters."""
    for task in PRE_EXECUTED[:2]:
        _save(task, pre_executed=True, session_id="pre-executed:9f9f9f9f9f9f")

    page = _flat(client.get("/").text)
    assert "9f9f9f9f9f9f" in page
    assert "seeded once and then kept" in page


def test_the_page_only_claims_the_buttons_re_run_the_demonstrations_when_they_do(client):
    """Three of four demo rows differed from the button that claimed to be them, and a
    grader pressing one got a new run they believed was a re-run."""
    _save(CHIPS[-1], pre_executed=True, session_id="pre-executed:x")
    assert "was submitted from one of these buttons" in _flat(client.get("/").text)

    _save("Is any product priced over £100?", pre_executed=True, session_id="pre-executed:x")
    page = _flat(client.get("/").text)
    assert "was submitted from one of these buttons" not in page
    assert "earlier wording" in page


def test_every_seeded_demonstration_is_offered_as_a_button():
    """The two lists are one list. They drifted apart the moment they were edited
    separately, and nothing compared them."""
    assert set(PRE_EXECUTED) <= set(CHIPS)


def test_the_buttons_render_the_task_strings_verbatim(client):
    """`fill()` copies the button's own text into the box, so a button that renders a
    truncated or escaped task submits a different task than the row it claims to re-run."""
    page = client.get("/").text
    rendered = re.findall(r'<button type="button" class="ghost" onclick="fill\(this\)">'
                          r'(.*?)</button>', page, re.S)
    import html

    assert [html.unescape(t.strip()) for t in rendered] == list(CHIPS)


# ---- getting into a run at the default width ----------------------------------------

def test_the_link_into_a_run_is_pinned_and_the_whole_row_carries_it(client):
    """Measured off-screen at the default width, with no scroll affordance, while both
    guides open by telling a reader to click into a run."""
    run = _save("Search the fixture catalogue for lantern")
    page = client.get("/").text

    row = re.search(rf"<tr[^>]*>(?:(?!</tr>).)*{run.id}(?:(?!</tr>).)*</tr>", page, re.S)
    assert row, "the run is not on the page at all"
    assert f'data-href="/runs/{run.id}"' in row.group(0)
    assert re.search(rf'<td class="pin"><a href="/runs/{run.id}">inspect</a></td>',
                     row.group(0))


def test_the_full_task_text_is_in_the_title_attribute(client):
    """The column truncates at ~40 characters and step 8 of the grader guide is a
    task-string comparison against /support."""
    long_task = ("On the Wikipedia article for Apple Inc., expand the first collapsed box "
                 "at the foot of the page and tell me its title and the label of its first "
                 "row group.")
    run = _save(long_task)
    page = client.get("/").text

    row = re.search(rf"<tr[^>]*>(?:(?!</tr>).)*{run.id}(?:(?!</tr>).)*</tr>", page, re.S)
    title = re.search(r'<td title="([^"]*)"', row.group(0))
    assert title, "the task cell carries no title attribute"
    import html

    assert html.unescape(title.group(1)) == long_task
    assert long_task not in row.group(0).replace(title.group(1), ""), (
        "the visible cell is still truncated; the title is where the whole string lives")


# ---- a run in flight -----------------------------------------------------------------

def _in_flight(task: str = "Read page 2 of the fixture browse listing") -> Run:
    from app import server

    run = Run(id=new_id("run"), task=task, tier=Tier.DECLARED, state=RunState.RUNNING)
    run.started_at = 1.0
    run.add(TraceEntry(seq=1, kind=StepKind.NAVIGATE, summary="Navigate to /browse", ok=True))
    run.add(TraceEntry(seq=2, kind=StepKind.EXTRACT, summary="Snapshot captured: step-2",
                       ok=True))
    server.state.store.save_run(run)
    for entry in run.trace:
        server.state.store.save_trace_entry(run.id, entry)
    return run


def test_a_running_run_says_it_has_no_claim_yet_rather_than_none(client):
    run = _in_flight()
    assert "No claim yet" in _flat(client.get(f"/runs/{run.id}").text)

    from app import server

    run.state = RunState.DONE
    run.terminal_status = TerminalStatus.FAILED
    server.state.store.save_run(run)
    page = _flat(client.get(f"/runs/{run.id}").text)
    assert "No claim was produced." in page and "No claim yet" not in page


def test_the_progress_line_carries_the_step_budget_the_executor_enforces(client):
    """`Step 11 / 25` — and the 25 comes from the setting, not from a number typed next to
    it in the template. A run that ended `budget_exhausted` never signalled the cap."""
    run = _in_flight()
    page = _flat(client.get(f"/runs/{run.id}").text)

    assert f"Step {run.budget.steps} / {settings.budgets.max_steps}" in page
    # The Budget panel and the heading read the same value, from the same place.
    assert f'id="live-steps">{run.budget.steps} of {settings.budgets.max_steps}<' in page


def test_the_progress_line_says_what_it_is_waiting_on(client):
    """"Waiting…" covered a queue, a browser context and a model call, which are minutes
    apart in what they mean."""
    from app import server

    run = _in_flight()
    run.add(TraceEntry(seq=3, kind=StepKind.NOTE,
                       summary="Model call (exploration) for step 3", ok=True))
    server.state.store.save_run(run)
    server.state.store.save_trace_entry(run.id, run.trace[-1])
    assert "waiting on the model" in _flat(client.get(f"/runs/{run.id}").text)

    fresh = Run(id=new_id("run"), task="x", tier=Tier.DECLARED, state=RunState.QUEUED)
    server.state.store.save_run(fresh)
    assert "waiting for a browser context" in _flat(client.get(f"/runs/{fresh.id}").text)


def test_the_progress_line_does_not_put_two_meanings_of_step_in_one_sentence(client):
    """`Step 11: Snapshot captured: step-2` — an execution count and a plan-step name."""
    run = _in_flight()
    page = client.get(f"/runs/{run.id}").text

    line = re.search(r'<p class="sub" id="progress">(.*?)</p>', page, re.S).group(1)
    assert "Snapshot captured" in line
    assert "step-2" not in line


def test_a_failed_optional_claim_is_labelled_optional(client):
    """A red `not verified` on a `succeeded_verified` run is correct and unexplained. Which
    claims are optional is read from the frozen postcondition, not from the verdict."""
    from app import server

    run = Run(id=new_id("run"), task="Search the fixture catalogue for lantern",
              tier=Tier.DECLARED, state=RunState.DONE,
              terminal_status=TerminalStatus.SUCCEEDED_VERIFIED)
    run.postcondition = {"claims": [{"name": "items", "optional": False},
                                    {"name": "empty_state", "optional": True}]}
    run.claims = [{"name": "items", "ok": True},
                  {"name": "empty_state", "ok": False, "failure_class": "locator_not_found"}]
    server.state.store.save_run(run)

    page = client.get(f"/runs/{run.id}").text
    block = re.search(r"<strong>empty_state</strong>.*?</p>", page, re.S).group(0)
    assert "optional" in block
    required = re.search(r"<strong>items</strong>.*?</p>", page, re.S).group(0)
    assert "optional" not in required


# ---- the session allowance -----------------------------------------------------------

def test_a_refused_run_does_not_spend_the_session_allowance(client):
    """The run row is written before admission, on purpose, so a refusal is inspectable.
    Counting those rows charged a visitor for capacity they were refused — and the cap is a
    lifetime count behind a cookie that lives a day, so it never came back."""
    from app import server
    from app.models import FailureClass

    store = server.state.store
    for i in range(3):
        _save(f"accepted {i}", session_id="sid-1")
    for i in range(4):
        run = Run(id=new_id("run"), task=f"refused {i}", tier=Tier.DECLARED,
                  state=RunState.DONE, session_id="sid-1",
                  terminal_status=TerminalStatus.BLOCKED,
                  failure_class=FailureClass.QUEUE_FULL if i % 2 else
                  FailureClass.SESSION_QUOTA)
        store.save_run(run)

    assert store.session_run_count("sid-1") == 3


def test_the_cap_that_can_stop_a_reader_is_published(client, monkeypatch):
    """`concurrency` and `depth` were on /healthz and this one was not, though it is the
    only one a visitor reaches by reading the site rather than by hammering it."""
    from app import server

    # The browser in this process belongs to whichever test started one; the endpoint under
    # test here is the queue block, not liveness.
    monkeypatch.setattr(server.state.supervisor, "status", lambda: {"connected": True})
    queue = client.get("/healthz").json()["queue"]
    assert queue["session_run_cap"] == settings.queue.session_run_cap


def test_the_refusal_says_how_to_carry_on(client):
    """A designed refusal that leaves a reader stuck for 24 hours with no next step is a
    dead end with a nice explanation."""
    from app.queue import SessionQuotaExceeded

    message = SessionQuotaExceeded(settings.queue.session_run_cap).message
    assert str(settings.queue.session_run_cap) in message
    assert "new private window" in message

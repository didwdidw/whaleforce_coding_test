"""Locator memory — the self-maintenance mechanism (§8, reduced by A25.6).

Deliberately small, and the tests are written against the boundaries rather than the
feature, because the boundaries are what make it safe to have at all:

- nothing enters memory except from a `succeeded_verified` run;
- a remembered locator is a hint that is re-resolved and re-verified, never an authority,
  and never a value;
- three consecutive failures quarantine a row, because a locator that has stopped working
  costs a step and a diagnosis before the run gets to where it would have started without
  it;
- a stale row is an absence with a reason, not a silent miss.
"""

from __future__ import annotations

import json
import time

import pytest

from app import memory as memory_module
from app.memory import LocatorMemory
from app.models import (
    FailureClass, Run, StepKind, TerminalStatus, Tier, TraceEntry, new_id,
)
from app.store import Store

ORIGIN = "https://books.toscrape.com"
IDENTITY = {"tag": "a", "role": "link", "name": "Next", "id": "next-page",
            "text": "next", "resolved": True}


@pytest.fixture()
def mem(tmp_path) -> LocatorMemory:
    return LocatorMemory(Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts"))


def test_a_step_with_no_element_is_not_a_locator(tmp_path):
    """The deterministic verification step is an `extract` with no element. Without this it
    wrote an empty row that could never match anything and held the key a real one needs."""
    from app.executor import Executor
    from app.models import Run, StepKind, TerminalStatus, Tier, TraceEntry, new_id

    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    executor = Executor.__new__(Executor)
    executor._locator_memory = LocatorMemory(store)
    run = Run(id=new_id("run"), task="t", tier=Tier.DECLARED)
    run.postcondition = {"operation": "OP-6", "target_url": f"{ORIGIN}/x"}
    run.trace = [TraceEntry(seq=1, kind=StepKind.EXTRACT, summary="Deterministic verification",
                            ok=True, detail={"locator_provenance": "freshly derived"})]
    run.terminal_status = TerminalStatus.SUCCEEDED_VERIFIED

    executor._write_back_locators(run)

    assert LocatorMemory(store).stats()["rows_stored"] == 0


def test_a_written_locator_comes_back(mem):
    mem.remember(origin=ORIGIN, operation="OP-6", role="link", identity=IDENTITY,
                 run_id="run_1")
    got = mem.recall(ORIGIN, "OP-6", "link")
    assert got is not None
    assert got.identity == IDENTITY
    assert got.stale is False


def test_an_absence_says_which_kind_of_absence_it_is(mem):
    """A11.8 applied to memory. Empty, expired and quarantined are three different facts,
    and a caller that gets `None` from all three cannot tell them apart."""
    assert "nothing remembered" in mem.why_not(ORIGIN, "OP-6", "link")

    mem.remember(origin=ORIGIN, operation="OP-6", role="link", identity=IDENTITY,
                 run_id="run_1")
    assert mem.why_not(ORIGIN, "OP-6", "link") == ""

    for _ in range(memory_module.QUARANTINE_AFTER):
        mem.used(ORIGIN, "OP-6", "link", worked=False)
    assert "quarantined" in mem.why_not(ORIGIN, "OP-6", "link")
    assert mem.recall(ORIGIN, "OP-6", "link") is None


def test_a_success_clears_the_failure_count(mem):
    """A locator that works is not on a countdown."""
    mem.remember(origin=ORIGIN, operation="OP-6", role="link", identity=IDENTITY,
                 run_id="run_1")
    mem.used(ORIGIN, "OP-6", "link", worked=False)
    mem.used(ORIGIN, "OP-6", "link", worked=False)
    mem.used(ORIGIN, "OP-6", "link", worked=True)
    mem.used(ORIGIN, "OP-6", "link", worked=False)

    assert mem.recall(ORIGIN, "OP-6", "link") is not None, "two failures is not three"


def test_a_row_nobody_has_re_confirmed_goes_stale_rather_than_lying(mem, monkeypatch):
    mem.remember(origin=ORIGIN, operation="OP-6", role="link", identity=IDENTITY,
                 run_id="run_1")
    monkeypatch.setattr(memory_module, "TTL_SECONDS", -1)
    assert mem.recall(ORIGIN, "OP-6", "link") is None
    assert "confirmation window" in mem.why_not(ORIGIN, "OP-6", "link")


def test_a_write_from_a_later_verified_run_releases_a_quarantine(mem):
    """The run that wrote it verified its answer, which is stronger evidence than the
    history that quarantined the row."""
    mem.remember(origin=ORIGIN, operation="OP-6", role="link", identity=IDENTITY,
                 run_id="run_1")
    for _ in range(memory_module.QUARANTINE_AFTER):
        mem.used(ORIGIN, "OP-6", "link", worked=False)
    assert mem.recall(ORIGIN, "OP-6", "link") is None

    healed = {**IDENTITY, "id": "pager-next"}
    mem.remember(origin=ORIGIN, operation="OP-6", role="link", identity=healed,
                 run_id="run_2", healed=True)

    got = mem.recall(ORIGIN, "OP-6", "link")
    assert got is not None and got.identity["id"] == "pager-next"
    assert mem.stats()["heals"] == 1


# ---- the write-back gate ----------------------------------------------------------

def _run_with_click(store: Store, status: TerminalStatus) -> Run:
    run = Run(id=new_id("run"), task="page forward", tier=Tier.DECLARED)
    run.postcondition = {"operation": "OP-6", "target_url": f"{ORIGIN}/catalogue/page-1.html"}
    entry = TraceEntry(seq=1, kind=StepKind.CLICK, summary="Click next", ok=True,
                       detail={"element": IDENTITY, "url": f"{ORIGIN}/catalogue/page-1.html"})
    entry.finished_at = time.time()
    run.trace = [entry]
    run.terminal_status = status
    store.save_run(run)
    return run


@pytest.mark.parametrize("status,remembered", [
    (TerminalStatus.SUCCEEDED_VERIFIED, True),
    (TerminalStatus.PARTIAL, False),
    (TerminalStatus.UNVERIFIED, False),
    (TerminalStatus.FAILED, False),
    (TerminalStatus.NO_RESULT_VERIFIED, False),
])
def test_only_a_verified_run_writes_to_memory(tmp_path, status, remembered):
    """The gate is the *run's* terminal status, not the step's. A click that worked on a run
    whose answer nobody could re-resolve is precisely the locator not to reuse, and writing
    on step success is how a memory fills with elements that were reachable and wrong."""
    from app.executor import Executor

    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    executor = Executor.__new__(Executor)
    executor._locator_memory = LocatorMemory(store)
    run = _run_with_click(store, status)

    executor._write_back_locators(run)

    got = LocatorMemory(store).recall(ORIGIN, "OP-6", "link")
    assert (got is not None) is remembered


def test_the_key_is_the_origin_not_the_url(tmp_path):
    """A listing and its page two are the same site and the same control. Keying on the URL
    would remember each page separately and match none of them twice."""
    from app.executor import Executor

    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    executor = Executor.__new__(Executor)
    executor._locator_memory = LocatorMemory(store)
    run = _run_with_click(store, TerminalStatus.SUCCEEDED_VERIFIED)
    run.trace[0].detail["url"] = f"{ORIGIN}/catalogue/page-7.html"

    executor._write_back_locators(run)

    assert LocatorMemory(store).recall(ORIGIN, "OP-6", "link") is not None


# ---- what a remembered identity is asked for --------------------------------------

def test_the_page_is_asked_in_its_own_vocabulary_first():
    """An accessible name and a role belong to the page; a CSS selector we once wrote down
    belongs to us, and is the weakest thing here — so it is tried last."""
    from app.executor import _selectors_for

    order = _selectors_for({**IDENTITY, "testid": "pager", "title": "Next page",
                            "recorded_as": ("li.next a",)})

    assert order[0] == '[role="link"]:text-is("Next")'
    assert order[-1] == "li.next a"
    assert list(order) == list(dict.fromkeys(order)), "no selector is tried twice"


def test_memory_never_carries_a_value(mem):
    """The one thing that would make this a channel from a third-party page into an answer.
    A row holds an element's identity; there is no field a value could live in."""
    mem.remember(origin=ORIGIN, operation="OP-6", role="link", identity=IDENTITY,
                 run_id="run_1")
    stored = json.loads(mem._store.locator_row(ORIGIN, "OP-6", "link")["identity"])
    assert set(stored) <= {"tag", "role", "id", "name", "label", "text", "href", "title",
                           "testid", "recorded_as", "ref", "resolved"}


def test_the_health_endpoint_reports_counters_not_a_rate(mem):
    """A hit rate over a handful of rows reads as a measurement and is not one."""
    stats = mem.stats()
    assert set(stats) >= {"rows_stored", "hits", "uses", "heals", "quarantined",
                          "ttl_days", "written_from", "authority"}
    assert not any(k.endswith("_rate") for k in stats)
    assert stats["written_from"] == "succeeded_verified runs only"

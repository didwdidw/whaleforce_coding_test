"""When the model-driven loop is allowed to stop, and who decides.

The planner does not reliably notice that it is done. On the category listing it reached the
right page with its first action and then spent five more calls re-extracting it — seven
model calls for a task that needs one. That is not an aesthetic problem: RPD 500 is a hard
daily ceiling, and a 7× multiplier on calls is a 7× divisor on how many evaluation rounds fit
in a day.

The fix does not ask the model to judge better, because that is the same judgement that was
wrong. Code answers instead, and only from the frozen postcondition: every declared action
observed, and the plan's own read step yielding every required claim. These tests pin the two
properties that make that safe — it never fires before the declared interaction has happened,
and it decides by the same rule the verifier will apply afterwards.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

from app.executor import Executor, Plan
from app.models import Run, StepKind, TraceEntry, Tier, new_id
from app.postcondition import ClaimSpec, Postcondition, Relation, RequiredAction
from app.store import Store


class _Ctx:
    """Only what `_goal_already_met` touches. A browser would add nothing here."""

    def __init__(self, run):
        self.run = run
        self.candidate: dict = {}


def _postcondition(*, required: bool = True, optional_claim: bool = False) -> Postcondition:
    return Postcondition(
        goal="page through the listing",
        operation="OP-6",
        target_url="https://example.invalid/page-2",
        inputs={"page": 2},
        required_actions=((RequiredAction("click", "next", "paging is the capability"),)
                          if required else ()),
        claims=(ClaimSpec("items", "listing entries", Relation.LIST_ENUMERATION,
                          "text_list", optional=optional_claim),),
    )


def _plan(pc: Postcondition, candidate: dict) -> Plan:
    async def read(ctx):
        ctx.candidate = dict(candidate)

    return Plan("OP-6", "listing", pc, (), read_step=read)


@pytest.fixture()
def executor(tmp_path, monkeypatch) -> Executor:
    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    return Executor(supervisor=None, store=store)


def _run_with_click(target: str | None) -> Run:
    run = Run(id=new_id("run"), task="page through the listing", tier=Tier.EXPERIMENTAL)
    if target is not None:
        run.add(TraceEntry(seq=1, kind=StepKind.CLICK, summary=f"click {target}", ok=True,
                           detail={"element": {"tag": "a", "text": target,
                                               "href": "page-2.html"}}))
    return run


def test_the_loop_stops_once_the_postcondition_is_satisfiable(executor):
    run = _run_with_click("next")
    ctx = _Ctx(run)
    plan = _plan(_postcondition(), {"items": ["a", "b"]})

    assert asyncio.run(executor._goal_already_met(ctx, plan)) is True
    assert any("stops here" in t.summary for t in run.trace), (
        "stopping early has to be visible in the trace; an invisible shortcut is "
        "indistinguishable from the loop simply ending")


def test_it_does_not_stop_before_the_declared_action_has_happened(executor):
    """Reading the value without the interaction is the shortcut S-4.4 exists to catch, not
    a reason to stop. The run must go on and fail loudly if it never does it."""
    run = _run_with_click(None)
    plan = _plan(_postcondition(), {"items": ["a", "b"]})

    assert asyncio.run(executor._goal_already_met(_Ctx(run), plan)) is False


def test_it_does_not_stop_on_a_partly_read_candidate(executor):
    run = _run_with_click("next")
    for empty in ({}, {"items": []}, {"items": None}):
        plan = _plan(_postcondition(), empty)
        assert asyncio.run(executor._goal_already_met(_Ctx(run), plan)) is False


def test_a_postcondition_with_nothing_required_never_ends_the_loop_early(executor):
    """A11.7's shape: "no required claim failed" must never be read as "everything passed"."""
    run = _run_with_click("next")
    plan = _plan(_postcondition(optional_claim=True), {"items": ["a"]})

    assert asyncio.run(executor._goal_already_met(_Ctx(run), plan)) is False


def test_a_read_step_that_throws_means_not_yet_rather_than_done(executor):
    async def explode(ctx):
        raise RuntimeError("the table is not on this page")

    run = _run_with_click("next")
    plan = Plan("OP-6", "listing", _postcondition(), (), read_step=explode)

    assert asyncio.run(executor._goal_already_met(_Ctx(run), plan)) is False


def test_the_loop_and_the_verifier_apply_the_same_required_action_rule(executor):
    """A loop using a looser rule than the verifier would stop on runs the verifier then
    fails — trading model calls for false failures."""
    source = pathlib.Path("app/executor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "_goal_already_met")
    body = ast.get_source_segment(source, function) or ""
    assert "self._verifier.missing_actions" in body

    run = _run_with_click("something else entirely")
    pc = _postcondition()
    assert executor._verifier.missing_actions(run, pc)
    assert asyncio.run(executor._goal_already_met(_Ctx(run), _plan(pc, {"items": ["a"]}))) \
        is False


def test_stopping_early_cannot_reach_a_verdict_by_itself(executor):
    """The safety property the whole change rests on: it ends the loop, it does not end the
    run. A premature stop still goes through the verifier and still has to survive
    re-extraction from the stored artifact."""
    source = pathlib.Path("app/executor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "_goal_already_met")
    body = ast.get_source_segment(source, function) or ""
    for forbidden in ("_terminate", "terminal_status", "TerminalStatus"):
        assert forbidden not in body, (
            f"_goal_already_met touches {forbidden}; deciding to stop and deciding the "
            f"outcome must stay separate")

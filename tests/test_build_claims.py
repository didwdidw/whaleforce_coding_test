"""Every user-visible string must describe the build that is running (A13.3, A-37).

The support page said four operations were "not yet implemented" for a milestone after they
shipped. The submit form said out-of-surface tasks were attempted when they were refused
before any browsing. The no-route explanation still said there was no model in the loop.
Nothing was lying on purpose — prose has no reason to change when code does, and nothing
here could tell a current claim from a stale one.

**A sentence about the state of the build is a claim, and a stale claim is a false one.** So
the build-state text is derived from `app/buildstate.py`, and these tests are what stops it
being retyped as prose next time.
"""

from __future__ import annotations

import html
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app.buildstate import MILESTONE, state
from app.demo import CHIPS, PRE_EXECUTED
from app.server import app

TEMPLATES = sorted((pathlib.Path(__file__).parent.parent / "app" / "templates").glob("*.html"))


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    with TestClient(app) as client:
        return {path: client.get(path).text for path in ("/", "/support")}


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_no_template_hard_codes_the_current_milestone(template):
    """It has to come from `build.milestone`, or the day the milestone changes there is a
    page still claiming the old one. Naming a *future* milestone is fine — that is a
    statement about what is absent, and it is guarded by the flag for the thing itself."""
    text = template.read_text(encoding="utf-8")
    assert not re.search(rf"\b{MILESTONE}\b", text), (
        f"{template.name} hard-codes {MILESTONE}; render {{{{ build.milestone }}}} instead")


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_no_template_repeats_a_claim_that_has_already_gone_stale_once(template):
    """These exact phrases were live and false. Keeping the list is cheaper than
    rediscovering them."""
    text = template.read_text(encoding="utf-8").lower()
    for phrase in ("not yet implemented", "no model is in the", "no model in the loop",
                   "this build is m"):
        assert phrase not in text, f"{template.name} contains a stale build claim: {phrase!r}"


def test_the_frontend_renders(pages):
    assert "Submit a task" in pages["/"]
    assert "What is promised" in pages["/support"]


def test_the_pages_agree_with_the_build_state(pages):
    """The claim and the flag are checked against each other, in the direction that
    matters: the page may not promise a path the build does not have."""
    build = state()
    home, support = pages["/"], pages["/support"]
    if build["generic_loop"]:
        assert "stops before browsing" not in home
    else:
        assert "stops before browsing" in home
        assert "not in this build" in support
    if build["planner_is_default"]:
        assert "planned by the model by default" in home


def test_the_support_matrix_marks_every_reachable_record_implemented(pages):
    build = state()
    assert pages["/support"].count("implemented (") == build["records_reachable"]


def test_the_offered_tasks_are_the_ones_that_can_run(pages):
    """A chip is an offer. One that routes nowhere is the frontend inviting a refusal."""
    for task in CHIPS:
        assert html.escape(task) in pages["/"], f"chip not rendered: {task!r}"


def test_every_promised_chip_routes_to_the_record_it_names():
    """The chips are how a reviewer reaches the promised surface without knowing our
    phrasing. One that routes to two operations abstains, and the abstention is ours."""
    from app.demo import PROMISED_TASKS
    from app.executor import RECORD_BY_ROUTE, Executor

    executor = Executor.__new__(Executor)
    reached = set()
    for task in PROMISED_TASKS:
        operation, candidates, _hits = executor.route(task)
        assert operation in RECORD_BY_ROUTE, (
            f"chip routes to {operation!r} (candidates {candidates}): {task!r}")
        reached.add(RECORD_BY_ROUTE[operation].id)
    assert reached == {r.id for r in RECORD_BY_ROUTE.values()}


def test_the_pre_executed_runs_need_no_provider():
    """They are what a visitor can inspect when the free tier is spent, so they must not be
    among the tasks that get planned by the model."""
    from app.config import settings
    from app.executor import Executor

    executor = Executor.__new__(Executor)
    executor._provider = type("P", (), {"configured": staticmethod(lambda: True)})()
    for task in PRE_EXECUTED:
        plan = executor._select_plan(task)
        if plan is None:  # the refusal demonstration never reaches a plan
            continue
        planned, _why = executor._choose_path(plan, False, False)
        assert not planned, f"pre-executed task would spend model quota: {task!r}"
        assert not plan.entry_url or settings.fixture_base_url in plan.entry_url

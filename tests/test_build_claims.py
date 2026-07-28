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


# --- known limitations are tasks, not cautions (A14.8) -------------------------------

def test_every_limitation_names_a_task_an_outcome_and_a_reason():
    """A limitation a reader cannot reproduce is a disclaimer. The four fields are what
    make it checkable against the deployed system."""
    from app.limitations import LIMITATIONS

    assert LIMITATIONS, "the list must not be empty"
    for limit in LIMITATIONS:
        assert len(limit.task) > 20, f"{limit.id}: the task must be one a person would type"
        assert limit.what_happens and limit.why, f"{limit.id}: incomplete"


def test_every_limitation_ends_in_a_declared_terminal_status():
    """An outcome outside the closed set is a typo that would send a reader looking for a
    status the system cannot produce."""
    from app.limitations import LIMITATIONS
    from app.models import FailureClass, TerminalStatus

    statuses = {s.value for s in TerminalStatus}
    classes = {f.value for f in FailureClass}
    for limit in LIMITATIONS:
        assert limit.outcome in statuses, f"{limit.id}: {limit.outcome}"
        assert limit.failure_class is None or limit.failure_class in classes, limit.id


def test_the_support_page_lists_them(pages):
    from app.limitations import LIMITATIONS

    body = pages["/support"]
    for limit in LIMITATIONS:
        assert limit.outcome in body
        assert limit.task[:40] in body.replace("&#39;", "'").replace("&amp;", "&")


# --- the published documents against the code they describe --------------------------

REPO = pathlib.Path(__file__).parent.parent
README = REPO / "README.md"
ANALYSIS = REPO / "docs" / "analysis-report.md"


def test_the_readme_limitations_table_carries_the_tasks_that_are_actually_executed():
    """`app/limitations.py` is the list `eval.limitations_check` runs against the
    deployment; the README table is prose beside it. They diverged — the table advertised a
    Project Gutenberg task for L-5 while the executed entry was an MDN compatibility grid,
    and the same section's own bullets said so three paragraphs further down. A limitations
    section that contradicts itself is worse than none, so the table is checked against the
    code rather than against a reviewer's attention."""
    from app.limitations import LIMITATIONS

    rows = dict(re.findall(r"^\|\s*\*\*(L-\d+)\*\*\s*\|(.+?)\|", README.read_text("utf-8"),
                           re.M))
    assert set(rows) == {limit.id for limit in LIMITATIONS}, "every entry has a row"
    for limit in LIMITATIONS:
        published = re.sub(r"\s+", " ", html.unescape(rows[limit.id])).strip().strip("*").strip('*"')
        expected = re.sub(r"\s+", " ", limit.task).rstrip(".")
        assert expected in published or published.rstrip('."') in expected, (
            f"{limit.id}: the README advertises a task the executed list does not carry.\n"
            f"  README: {published}\n  code:   {expected}")


def test_the_readme_states_the_outcome_the_code_produces_for_each_limitation():
    """The other half of the same divergence: L-7's row described an abstention while the
    entry had become a proven absence. The task column and the outcome column have to be
    about the same thing."""
    from app.limitations import LIMITATIONS

    rows = dict(re.findall(r"^\|\s*\*\*(L-\d+)\*\*\s*\|.+?\|(.+?)\|\s*$",
                           README.read_text("utf-8"), re.M))
    for limit in LIMITATIONS:
        text = rows[limit.id].lower()
        named = [word for word in (limit.outcome, limit.failure_class) if word
                 and (word in text or word.replace("_", " ") in text)]
        assert named, (f"{limit.id}: the row does not say the run ends in "
                       f"`{limit.outcome}` / `{limit.failure_class}`")


#: Money written as words. Every real figure in these documents is `USD x.xxxx` in a table
#: or is in the ledger, so this vocabulary only ever appears as a total in disguise — and a
#: total in words goes stale exactly as fast as one in digits while looking like commentary.
MONEY_IN_WORDS = re.compile(r"(?i)\b(cents?|dollars?|pennies|a tenth of a)\b")

#: A claim about what was spent *in total*, as opposed to a price or a per-unit figure.
A_TOTAL = re.compile(r"(?i)\b(total|totals|cumulative|altogether|across every|"
                     r"across all|all development)\b")
SPEND = re.compile(r"(?i)\b(spend|outlay|bill)\b")
AN_AMOUNT = re.compile(r"(?i)(\bUSD\b|\$\d|\d+\.\d)")


def test_no_published_document_states_a_spend_total_of_its_own():
    """Three documents each carried one, all three went stale on the same day, and one was
    false rather than merely old. The generated ledger is the only place a total lives.

    Two rules, because the first version of this test looked for digits and the first thing
    to slip past it was *"under a tenth of a dollar"* — the same stale total, spelled out,
    on a wrapped line that no longer contained the word `spend`. `--check` regenerates a
    file; it cannot read a sentence, so the sentences are what this has to cover.
    """
    for path in (README, ANALYSIS):
        text = path.read_text("utf-8")
        assert "spend-ledger.md" in text, f"{path.name} must link to the ledger"
        spelled = MONEY_IN_WORDS.findall(text)
        assert not spelled, (
            f"{path.name} writes an amount in words ({spelled}); every figure belongs in a "
            f"table or in the generated ledger, where something keeps it true")
        for block in re.split(r"\n\s*\n", text):
            if not (SPEND.search(block) and A_TOTAL.search(block)):
                continue
            if "spend-ledger.md" in block:
                continue          # a block whose subject is the ledger itself
            assert not AN_AMOUNT.search(block), (
                f"{path.name} states a spend total of its own:\n  {block.strip()[:200]}")


def test_the_r3_markers_are_present_until_r3_is_committed_and_gone_afterwards():
    """The two places holding numbers that are known to be wrong in a known direction.

    `r2`'s dev split ran on the build *before* Amendment 26, so OP-5's "1 of 2" is the
    redirect gate failing a correct run rather than the operation. Shipping that as the
    published rate would be publishing a figure we already know is low. The marker is a
    note to a reader of the source; this is what makes forgetting it a test failure —
    the moment an r3 result lands in `eval/results/`, the markers have to be resolved."""
    scored_r3 = sorted((REPO / "eval" / "results").glob("*-r3.json"))
    markers = README.read_text("utf-8").count("<!-- FROM-r3")

    if not scored_r3:
        assert markers == 2, (
            "the support matrix and the evaluation section carry pre-r3 numbers and must "
            "say so until r3 replaces them")
    else:
        assert markers == 0, (
            f"r3 has been scored ({[p.name for p in scored_r3]}) — regenerate the support "
            f"matrix and §6 from it, then remove the FROM-r3 markers")


def test_the_committed_spend_ledger_is_up_to_date():
    """`--check` is what turns the next stale total into a test failure instead of
    something a reader finds."""
    from eval.spend_ledger import main

    assert main(["--check"]) == 0, "run `python -m eval.spend_ledger`"

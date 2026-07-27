"""The shared definition of element identity, and the drift it exists to prevent.

Three components have to agree on "the same element", and three times they did not: each
disagreement showed up as a run that took exactly the right action and was scored as having
skipped it, and each was fixed by appending a field to one of the three lists. These tests
are what makes the fourth time impossible to introduce quietly — the browser-side collector
and the Python dataclass are checked against each other, and every consumer is checked
against the same comparison rather than against a list of its own.
"""

from __future__ import annotations

import asyncio

import pytest

from app.identity import COLLECT_JS, FIELDS, ElementIdentity, normalise

PAGE = """
<a id="nx" class="next" href="/catalogue/page-2.html" title="Next page">next</a>
<a href="../a-light-in-the-attic_1000/index.html" title="A Light in the Attic">
  A Light in the Attic</a>
<button data-testid="basket-add">Add to basket</button>
<label for="q">Product name or code</label><input id="q" name="query" value="lantern">
<th class="headerSort" title="Sort ascending" role="columnheader">Founded</th>
<button aria-label="Dismiss notice">&times;</button>
"""


# --- the property that keeps the definitions from drifting -------------------------

@pytest.mark.integration
def test_the_collector_and_the_dataclass_cannot_drift():
    """The browser-side collector returns exactly the fields the dataclass declares.

    This is the test that has to exist. Adding a way to name an element without teaching
    every consumer about it is the defect that recurred three times; here it is a failure at
    the moment it is written rather than a mis-scored run on a real site weeks later.
    """
    from app.browser import BrowserSupervisor

    async def collect():
        sup = BrowserSupervisor()
        await sup.start()
        try:
            async with sup.context() as (context, _generation):
                page = await context.new_page()
                await page.set_content(f"<html><body>{PAGE}</body></html>")
                element = await page.query_selector("#nx")
                return await element.evaluate(COLLECT_JS)
        finally:
            await sup.aclose()

    collected = asyncio.run(collect())
    assert set(collected) == set(FIELDS), (
        "the browser collector and ElementIdentity have drifted; a field known to one and "
        "not the other is exactly how the required-action check went blind three times")

    identity = ElementIdentity.from_browser(collected, ref="e4")
    assert identity.id == "nx"
    assert identity.href == "/catalogue/page-2.html"
    assert identity.text == "next"
    assert identity.title == "Next page"


# --- what an element answers to ---------------------------------------------------

def _pager() -> ElementIdentity:
    return ElementIdentity(tag="a", id="nx", text="next", title="Next page",
                           href="/catalogue/page-2.html", ref="e4")


@pytest.mark.parametrize("target,field", [
    ("#next", "text"),              # a postcondition naming a CSS id selector
    ("next", "text"),               # the same target unadorned
    ("nx", "id"),                   # the DOM id
    ("page-2", "href"),             # the declared target, which is often all a link has
    ("Next page", "title"),
])
def test_one_element_is_recognised_by_every_handle_it_publishes(target, field):
    assert _pager().match(target) == field


def test_the_match_says_which_handle_recognised_it():
    """A match on `href` and a match on a step's own summary are different strengths of
    evidence and must not read the same afterwards."""
    weak = ElementIdentity(recorded_as=("li.next a", "Click 'next' to the second page"))
    assert weak.match("next") == "recorded_as"
    assert _pager().match("next") == "text"


def test_matching_is_whole_token_not_substring():
    """The comparison this replaced was `target in haystack` over a joined blob, which
    credits a declared action whenever the target happens to appear inside anything. A
    false positive here marks an action as performed when it was not, which is the one
    direction that must not be loose."""
    resort = ElementIdentity(tag="a", text="Resorts and hotels", href="/resort/index.html")
    assert resort.match("sort") is None
    assert ElementIdentity(text="Sort ascending").match("sort") == "text"


def test_an_empty_target_matches_nothing():
    assert _pager().match("") is None
    assert _pager().match("#") is None


def test_an_href_matches_by_path_segment_not_by_accident():
    """On a real site the declared target is a path fragment and the visible text is a
    human-readable title, so the two never match each other — OP-7's failure."""
    thumbnail = ElementIdentity(tag="a", href="../a-light-in-the-attic_1000/index.html")
    assert thumbnail.match("a-light-in-the-attic") == "href"
    assert thumbnail.match("A Light in the Attic") == "href"  # slug and title agree once
                                                              # both are normalised
    titled = ElementIdentity(tag="a", text="A Light in the Attic")
    assert titled.match("a-light-in-the-attic") == "text"


def test_identity_reports_only_what_it_knows():
    """A view full of nulls costs tokens and says nothing."""
    d = ElementIdentity(tag="a", text="next", ref="e4").to_dict()
    assert d == {"tag": "a", "text": "next", "ref": "e4"}


def test_an_unresolved_ref_says_so_rather_than_looking_empty():
    identity = ElementIdentity(ref="e9", resolved=False)
    assert identity.to_dict() == {"ref": "e9", "resolved": False}
    assert identity.match("anything") is None


# --- the consumers all go through it ----------------------------------------------

def test_the_scripted_path_and_the_planned_path_resolve_the_same_target():
    """The two routes record different things — a CSS selector, and a resolved element —
    and the declared target has to find both. This is the M3 defect, as a test."""
    scripted = ElementIdentity.from_trace(
        {"selector": "li.next a"}, "Click 'next' to the second page")
    planned = ElementIdentity.from_trace(
        {"element": {"tag": "a", "id": "nx", "text": "next",
                     "href": "/catalogue/page-2.html", "ref": "e4"}}, "click e4")
    assert scripted.matches("next") and planned.matches("next")


def test_the_verifier_owns_no_field_list_of_its_own():
    """Structural, because the comment above the old implementation promised the same thing
    and the list underneath it still grew twice."""
    import ast
    import pathlib

    source = pathlib.Path("app/verifier.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_missing_actions")
    body = ast.get_source_segment(source, function) or ""
    strayed = [f for f in ("href", "title", "name_attr", "innerText") if f in body]
    assert not strayed, (
        f"_missing_actions names element fields directly ({strayed}); identity belongs to "
        f"app.identity, and a second copy of the list is how the first three defects "
        f"survived")


def test_the_reducer_uses_the_shared_collector_rather_than_its_own():
    from app.reduce import REDUCE_JS

    assert COLLECT_JS.strip() in REDUCE_JS
    assert "__IDENTITY__" not in REDUCE_JS


def test_normalisation_is_shared_by_both_sides_of_the_comparison():
    assert normalise("#Next-Page ") == "next page"
    assert normalise("../a-light-in-the-attic_1000/index.html") == (
        "a light in the attic 1000 index html")
    assert normalise(None) == ""

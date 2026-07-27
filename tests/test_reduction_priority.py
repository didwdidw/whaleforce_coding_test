"""What the reduced view is allowed to throw away when it runs out of budget.

The element cap is not optional — an unbounded view is an unbounded prompt — so the question
is never *whether* elements are dropped but *which*. Dropping by document order lost a
category listing's single pagination link behind twenty sidebar links and twenty repeated
"Add to basket" buttons, and the model, shown a page with no pagination, abstained. It was
right about what it had been given. Nothing downstream could tell that apart from a page
that genuinely had no pager, because both produce the same honest refusal.

So the rule is asserted here rather than left to ranking that happens to work: an element the
goal names survives the cap, and identical repeated affordances do not crowd out unique ones.
"""

from __future__ import annotations

import asyncio

import pytest

from app.reduce import reduce_page

pytestmark = pytest.mark.integration

#: One element the goal names, buried behind far more elements than the cap allows — the
#: shape of the real page, without depending on the real page.
CROWDED = """
<html><body>
  <div class="side_categories"><ul>{sidebar}</ul></div>
  <section id="content_inner">
    <ol>{products}</ol>
    <ul class="pager"><li class="next"><a href="page-2.html">next</a></li></ul>
  </section>
</body></html>
"""


def _page_html(sidebar: int = 25, products: int = 40) -> str:
    return CROWDED.format(
        sidebar="".join(f'<li><a href="/c/{i}">Nonfiction topic {i}</a></li>'
                        for i in range(sidebar)),
        products="".join(
            f'<li><article class="product_pod"><h3><a href="/b/{i}" title="Book {i}">'
            f'Book {i}</a></h3><button>Add to basket</button></article></li>'
            for i in range(products)),
    )


async def _reduce(html: str, terms, **overrides):
    from app.browser import BrowserSupervisor

    sup = BrowserSupervisor()
    await sup.start()
    try:
        async with sup.context() as (context, _generation):
            page = await context.new_page()
            await page.set_content(html)
            return await reduce_page(page, terms, **overrides)
    finally:
        await sup.aclose()


def test_an_element_the_goal_names_survives_the_cap():
    """The regression. `next` is the last interactive element in document order and the one
    the task cannot be done without."""
    view = asyncio.run(_reduce(_page_html(), ("results", "showing", "next", "Nonfiction")))

    kept = view["interactive"]
    assert len(kept) <= view["limits"]["maxInteractive"]
    pager = [e for e in kept if e.get("href") == "page-2.html"]
    assert pager, (
        "the pagination link the goal names was dropped; the model will be shown a page "
        "with no pager and will correctly say so, and the run will fail as an abstention "
        "that looks exactly like an honest one")
    assert pager[0].get("names_goal_term") is True


def test_repeated_affordances_do_not_crowd_out_unique_elements():
    """Forty identical buttons are one affordance repeated. After a few, each copy costs
    budget without adding anything the planner can choose between."""
    view = asyncio.run(_reduce(_page_html(), ("next",)))

    baskets = [e for e in view["interactive"] if e.get("text") == "Add to basket"]
    assert len(baskets) <= view["limits"]["maxPerAffordance"]
    assert view["dropped"].get("interactive_repeated_affordance", 0) > 0
    titles = {e.get("title") for e in view["interactive"] if e.get("title")}
    assert len(titles) > 20, "unique product links were crowded out by identical buttons"


def test_dropping_a_goal_named_element_is_counted_under_its_own_name():
    """If it ever does happen, it must be attributable. A generic `over_cap` count cannot
    distinguish 'we trimmed some noise' from 'we trimmed the answer'."""
    view = asyncio.run(_reduce(_page_html(sidebar=80, products=2),
                               ("Nonfiction",), maxInteractive=10))

    assert view["dropped"].get("interactive_goal_term_over_cap", 0) > 0


def test_the_view_describes_elements_with_the_shared_identity_fields():
    """What the model is shown is what the required-action check will later look for. When
    those were separate lists, a run that clicked the right link was scored as having
    skipped it."""
    from app.identity import FIELDS

    view = asyncio.run(_reduce(_page_html(), ("next",)))
    keys = {k for e in view["interactive"] for k in e}
    described = keys & set(FIELDS)
    assert {"href", "text"} <= described
    assert not (keys - set(FIELDS) - {
        "ref", "role", "in_region", "names_goal_term", "table", "column_index",
        "type", "value", "state"}), f"the view invents element fields: {keys}"


# --- the selector policy answers to measurement ------------------------------------

def test_no_site_specific_selector_ships_unmeasured():
    """Naming one site's markup in a general component is a bet on a held-out site
    spelling it the same way, and an unmeasured bet is the worst kind.

    The CHROME list carried MediaWiki container names from the day it was written; they
    never once changed a reduced view, and nothing could distinguish that from them working.
    This test does not forbid site selectors. It forbids adding one without going through
    `preflight/selector_contribution.py` and recording what it is worth — which is what
    changing this test forces you to do.
    """
    from app.reduce import SELECTORS

    carried = {group: lists["site"] for group, lists in SELECTORS.items()
               if lists["site"]}
    assert not carried, (
        f"site-specific selectors present: {carried}. Run "
        f"preflight/selector_contribution.py, record the result in "
        f"docs/m4-selector-contribution.json, and state the assumption each one encodes.")


def test_removing_a_selector_is_something_the_code_supports():
    """The measurement harness has to keep working, or the rule above becomes unenforceable
    the first time someone changes how the script is built."""
    from app.reduce import SELECTORS, build_reduce_js, selector

    assert "a[href]" in selector("interactive")
    assert "a[href]" not in selector("interactive", without=("a[href]",))
    # Emptying a group must not produce a selector that throws in the browser.
    assert selector("chrome", without=SELECTORS["chrome"]["general"]) == ":not(*)"
    assert "__CHROME__" not in build_reduce_js()

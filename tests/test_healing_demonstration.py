"""One healing demonstration, on an archived real-page DOM (A14.6, A25.6).

Not the fixture. The fixture's mutations are ours, applied by us, to markup we wrote — good
enough to show the mechanism exists and not good enough to show it survives a page nobody
consulted us about. So this runs against **the real books.toscrape Nonfiction listing as it
was served**, archived byte for byte, and against a copy of that same page with the pager
rewritten the way a redesign rewrites things: new class, new wrapper, a `data-` hook where
there was none, and the accessible name left exactly as it was.

That asymmetry is the whole claim. `li.next a` is our spelling of the control and it does
not survive. *The link whose name is "next"* is the page's own spelling, and it does. The
memory's job is to have written down the second one on a run that verified its answer, so
that the run after the redesign has something better than a guess.

The demonstration is a browser driving the two archived files from disk — nothing is
simulated, and nothing reaches the network.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from app.executor import _selectors_for
from app.identity import COLLECT_JS, ElementIdentity
from app.memory import LocatorMemory
from app.store import Store

pytestmark = pytest.mark.integration

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
ARCHIVED = FIXTURES / "heal-books-nonfiction-p1.html"
REDESIGNED = FIXTURES / "heal-books-nonfiction-p1-redesigned.html"
ORIGIN = "https://books.toscrape.com"
#: What the plan for OP-6 asks the page for. Ours, not the page's.
SCRIPTED_SELECTOR = "li.next a"


@pytest.fixture(scope="module")
def browser():
    from playwright.async_api import async_playwright

    loop = asyncio.new_event_loop()

    async def start():
        p = await async_playwright().start()
        b = await p.chromium.launch()
        return p, b, await b.new_page()

    playwright, launched, page = loop.run_until_complete(start())
    yield loop, page
    loop.run_until_complete(launched.close())
    loop.run_until_complete(playwright.stop())
    loop.close()


def _open(loop, page, path: pathlib.Path):
    loop.run_until_complete(page.goto(path.as_uri(), wait_until="load"))


def test_the_scripted_selector_works_on_the_page_as_it_was(browser):
    loop, page = browser
    _open(loop, page, ARCHIVED)
    assert loop.run_until_complete(page.query_selector(SCRIPTED_SELECTOR)) is not None


def test_the_scripted_selector_does_not_survive_the_redesign(browser):
    """The premise. Without this the demonstration would be showing memory rescuing a run
    that was never in trouble."""
    loop, page = browser
    _open(loop, page, REDESIGNED)
    assert loop.run_until_complete(page.query_selector(SCRIPTED_SELECTOR)) is None


def test_a_verified_run_on_the_original_teaches_the_redesigned_page(browser, tmp_path):
    """The demonstration itself, end to end over the two archived pages.

    Step 1 — on the page as it was, the scripted selector resolves and the identity the
    *page* publishes is collected and written to memory, exactly as a `succeeded_verified`
    run writes it.

    Step 2 — on the redesigned page the scripted selector finds nothing. What memory
    remembers is re-resolved against the live DOM, the control is found by its accessible
    name, and the run continues. The locator moved from a structural family to a semantic
    one, which is what makes it a recovery rather than a retry.
    """
    loop, page = browser
    memory = LocatorMemory(Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts"))

    _open(loop, page, ARCHIVED)
    handle = loop.run_until_complete(page.query_selector(SCRIPTED_SELECTOR))
    identity = ElementIdentity.from_browser(
        loop.run_until_complete(handle.evaluate(COLLECT_JS)))
    memory.remember(origin=ORIGIN, operation="OP-6", role="link",
                    identity=identity.to_dict(), run_id="run_verified")

    _open(loop, page, REDESIGNED)
    assert loop.run_until_complete(page.query_selector(SCRIPTED_SELECTOR)) is None

    remembered = memory.recall(ORIGIN, "OP-6", "link")
    assert remembered is not None
    healed = None
    for candidate in _selectors_for(remembered.identity):
        found = loop.run_until_complete(page.query_selector(candidate))
        if found is not None:
            healed = (candidate, found)
            break

    assert healed is not None, (
        f"nothing in memory resolved on the redesigned page: "
        f"{_selectors_for(remembered.identity)}")
    candidate, found = healed
    # It is the pager that was found, not something else on the page with a similar name.
    assert loop.run_until_complete(found.get_attribute("href")) == "page-2.html"
    # And it was found by the page's own vocabulary rather than by one of our selectors.
    assert SCRIPTED_SELECTOR not in candidate

    memory.used(ORIGIN, "OP-6", "link", worked=True)
    assert memory.stats()["hits"] == 1


def test_the_healed_locator_is_still_verified_like_any_other(browser, tmp_path):
    """The boundary that makes memory safe to have. A remembered identity resolves an
    element; it does not carry a value, and nothing downstream treats what it found as
    established. The value read here still has to come off the page."""
    loop, page = browser
    memory = LocatorMemory(Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts"))
    _open(loop, page, ARCHIVED)
    handle = loop.run_until_complete(page.query_selector(SCRIPTED_SELECTOR))
    identity = ElementIdentity.from_browser(
        loop.run_until_complete(handle.evaluate(COLLECT_JS)))
    memory.remember(origin=ORIGIN, operation="OP-6", role="link",
                    identity=identity.to_dict(), run_id="run_verified")

    stored = memory.recall(ORIGIN, "OP-6", "link").identity

    assert "value" not in stored and "text_content" not in stored
    assert set(stored) <= {"tag", "role", "id", "name", "label", "text", "href", "title",
                           "testid", "recorded_as", "ref", "resolved"}

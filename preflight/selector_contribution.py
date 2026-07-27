"""What each site-specific selector in the reducer is actually worth, measured per page.

The CHROME list named MediaWiki containers from the day it was written. They never once
changed a reduced view, and nothing in the system could tell that apart from them working —
a rule that is inert and a rule that is load-bearing look identical unless someone removes it
and looks. They are gone now, and the same question is owed to every other site-specific
selector still in the file.

The reason is not tidiness. The held-out set runs on sites we have never seen. A rule that
does nothing on Wikipedia is harmless; a rule that *only* works on Wikipedia means our dev
numbers do not travel, and we will not find that out until the score comes back.

So, for every page the product actually runs against, and for every site-specific selector:
remove it, reduce again, and compare the views element by element.

- **No difference anywhere** → inert. Delete it; keeping it means keeping something nothing
  can distinguish from absent.
- **A difference** → it does something. Keep it, and write down the assumption it encodes,
  because that assumption is what a held-out site is free to violate.

Usage:  python -m preflight.selector_contribution
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import time

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("REQUIRE_PERSISTENT_STORE", "false")

from app import reduce as reduce_module                                    # noqa: E402
from app.browser import BrowserSupervisor                                  # noqa: E402
from app.config import settings                                            # noqa: E402
from app.reduce import SELECTORS, build_reduce_js, reduce_page             # noqa: E402

OUT = pathlib.Path(__file__).parent.parent / "docs" / "m4-selector-contribution.json"

#: Site-specific selectors this module used to carry. They are measured by being put *back*,
#: so the evidence that justified retiring them does not disappear along with them — a
#: measurement you cannot re-run is a claim, not a measurement.
RETIRED: tuple[tuple[str, str], ...] = (
    ("containers", "ul.pager"), ("containers", "div.product_main"),
    ("containers", "div.sub-header"), ("containers", "div.mw-collapsible"),
    ("containers", "div.side_categories"),
    ("candidate_text", "li.current"), ("candidate_text", "li.next"),
    ("interactive", "th.headerSort"), ("interactive", ".mw-collapsible-toggle"),
    ("interactive", "li.next a"), ("interactive", "li.previous a"),
    ("chrome", "#mw-panel"), ("chrome", "#mw-navigation"), ("chrome", "#vector-toc"),
    ("chrome", "#p-lang-btn"), ("chrome", ".mw-footer"), ("chrome", ".vector-header"),
    ("chrome", ".vector-sticky-header"), ("chrome", ".mw-jump-link"),
    ("chrome", ".mw-editsection"), ("chrome", ".navbar"), ("chrome", ".sitenav"),
    ("main", "#mw-content-text"), ("main", "#content_inner"),
    ("main", ".product_main"), ("main", ".page_inner"),
)

WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
BOOKS = "https://books.toscrape.com"

#: Every page a promised record runs against, plus the fixture pages the gate cases use.
#: A selector that does nothing here does nothing anywhere we can observe.
PAGES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("OP-4/OP-5 wikipedia article", WIKI,
     ("GICS Sector", "Symbol", "Security", "constituents", "Energy", "show")),
    ("OP-6 books category listing",
     f"{BOOKS}/catalogue/category/books/nonfiction_13/index.html",
     ("results", "showing", "next", "Nonfiction")),
    ("OP-7 books product detail",
     f"{BOOKS}/catalogue/a-light-in-the-attic_1000/index.html",
     ("UPC", "Availability", "Product Information", "A Light in the Attic")),
    ("fixture browse listing", f"{settings.fixture_base_url}/browse",
     ("Page", "of", "next", "results")),
    ("fixture gated page", f"{settings.fixture_base_url}/gated",
     ("Product code", "Stock on hand", "dismiss", "reveal")),
)


def _fingerprint(view: dict) -> dict:
    """Everything about a view that could change an outcome, in a comparable form."""
    return {
        "interactive": [
            {k: v for k, v in element.items() if k != "ref"}
            for element in view.get("interactive", [])
        ],
        "anchor_regions": [
            {k: v for k, v in region.items() if k != "ref"}
            for region in view.get("anchor_regions", [])
        ],
    }


async def _reduce_all(page, terms, arms: dict[str, str]) -> dict[str, dict]:
    out = {}
    for name, js in arms.items():
        reduce_module.REDUCE_JS = js
        out[name] = _fingerprint(await reduce_page(page, terms))
    reduce_module.REDUCE_JS = build_reduce_js()
    return out


def _describe(before: dict, after: dict) -> dict:
    """How the view changed, in the terms that matter: which elements and regions moved."""
    def keys(fingerprint, part):
        return [json.dumps(item, sort_keys=True) for item in fingerprint[part]]

    lost_elements = [k for k in keys(before, "interactive")
                     if k not in keys(after, "interactive")]
    gained_elements = [k for k in keys(after, "interactive")
                       if k not in keys(before, "interactive")]
    lost_regions = [k for k in keys(before, "anchor_regions")
                    if k not in keys(after, "anchor_regions")]
    gained_regions = [k for k in keys(after, "anchor_regions")
                      if k not in keys(before, "anchor_regions")]
    return {
        "changed": bool(lost_elements or gained_elements
                        or lost_regions or gained_regions),
        "elements_lost": len(lost_elements),
        "elements_gained": len(gained_elements),
        "regions_lost": len(lost_regions),
        "regions_gained": len(gained_regions),
        "examples_lost": [json.loads(k) for k in (lost_elements + lost_regions)[:3]],
    }


async def main() -> None:
    carried = [(group, entry, "carried")
               for group, lists in SELECTORS.items() for entry in lists["site"]]
    retired = [(group, entry, "retired") for group, entry in RETIRED]
    site_selectors = carried + retired

    arms = {"shipped": build_reduce_js()}
    for group, entry, status in site_selectors:
        # A carried selector is measured by taking it out; a retired one by putting it
        # back. Either way the comparison is against exactly what ships.
        arms[f"{group}:{entry}"] = (build_reduce_js(without=(entry,)) if status == "carried"
                                    else build_reduce_js(plus={group: (entry,)}))

    results: dict[str, dict[str, dict]] = {f"{g}:{e}": {} for g, e, _ in site_selectors}
    unreachable = []

    supervisor = BrowserSupervisor()
    await supervisor.start()
    try:
        async with supervisor.context() as (context, _generation):
            page = await context.new_page()
            for label, url, terms in PAGES:
                try:
                    await page.goto(url, wait_until="load", timeout=30_000)
                except Exception as exc:  # noqa: BLE001 - an unreachable page is a fact
                    unreachable.append({"page": label, "url": url, "error": str(exc)[:200]})
                    print(f"  UNREACHABLE {label}: {str(exc)[:80]}")
                    continue
                await page.wait_for_timeout(1500)
                views = await _reduce_all(page, terms, arms)
                print(f"\n{label}")
                for group, entry, _status in site_selectors:
                    key = f"{group}:{entry}"
                    diff = _describe(views["shipped"], views[key])
                    results[key][label] = diff
                    if diff["changed"]:
                        print(f"  CHANGES  {key:42} "
                              f"-{diff['elements_lost']}el -{diff['regions_lost']}rg")
    finally:
        await supervisor.aclose()
        reduce_module.REDUCE_JS = build_reduce_js()

    verdicts = {}
    print("\n--- verdict per selector ---")
    for group, entry, status in site_selectors:
        key = f"{group}:{entry}"
        pages_changed = [p for p, d in results[key].items() if d["changed"]]
        verdicts[key] = {
            "status": status,
            "pages_measured": len(results[key]),
            "pages_changed": pages_changed,
            "verdict": (("inert on every page measured" if not pages_changed
                         else f"changes the view on {len(pages_changed)} page(s)")
                        + (" — stays retired" if status == "retired" else
                           " — delete it" if not pages_changed else
                           " — keep, and write down the assumption it encodes")),
            "per_page": results[key],
        }
        mark = "INERT       " if not pages_changed else "CHANGES VIEW"
        print(f"  [{status[:7]:7}] {mark} {key:38} "
              f"{', '.join(pages_changed) or '-'}")

    OUT.write_text(json.dumps({
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
        "question": ("For each site-specific selector in the reducer: does removing it "
                     "change the reduced view of any page the product runs against?"),
        "why": ("The held-out set runs on sites we have not seen. A rule that does nothing "
                "on our pages is indistinguishable from absent and should go; a rule that "
                "only works on our pages means the dev numbers do not travel."),
        "pages": [{"label": label, "url": url} for label, url, _ in PAGES],
        "unreachable": unreachable,
        "verdicts": verdicts,
    }, indent=1), encoding="utf-8")
    print(f"\nwritten {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

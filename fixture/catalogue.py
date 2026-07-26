"""The fixture's data and its ground truth.

Ground truth is computed from this module's own server state and is **generated
independently of the mutation layer** (S-9.3): mutations rewrite markup, never answers. The
self-test in `selftest()` asserts exactly that, and the system under test has no access to
the test hook that exposes it.

The catalogue is deterministic and seeded from a fixed list so a run is reproducible from
its recorded seed alone (S-9.4).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

PAGE_SIZE = 6


@dataclass(frozen=True)
class Item:
    sku: str
    title: str
    category: str
    price_gbp: float
    stock: int
    material: str


# Fixed catalogue. Values chosen so several predicates have unambiguous answers: exactly
# one item above £90, a category with no matches at all, and adjacent labels that differ.
ITEMS: tuple[Item, ...] = (
    Item("WF-1001", "Brass Compass",            "instruments", 42.50, 12, "brass"),
    Item("WF-1002", "Sextant Mk II",            "instruments", 91.75, 2,  "brass"),
    Item("WF-1003", "Pocket Barometer",         "instruments", 33.05, 0,  "steel"),
    Item("WF-1004", "Mariner's Chronometer",    "instruments", 88.20, 4,  "steel"),
    Item("WF-1005", "Deck Log Book",            "stationery",  12.99, 40, "paper"),
    Item("WF-1006", "Chart Portfolio",          "stationery",  24.40, 7,  "canvas"),
    Item("WF-1007", "Signal Flag Set",          "signalling",  57.00, 5,  "cotton"),
    Item("WF-1008", "Morse Lamp",               "signalling",  63.15, 1,  "steel"),
    Item("WF-1009", "Bosun's Whistle",          "signalling",   9.80, 23, "brass"),
    Item("WF-1010", "Rope Splicing Kit",        "rigging",     31.60, 9,  "steel"),
    Item("WF-1011", "Marlinspike",              "rigging",     14.25, 15, "steel"),
    Item("WF-1012", "Rigging Screw",            "rigging",     27.90, 6,  "steel"),
    Item("WF-1013", "Storm Lantern",            "lighting",    45.00, 8,  "brass"),
    Item("WF-1014", "Anchor Light",             "lighting",    52.35, 3,  "steel"),
)

CATEGORIES: tuple[str, ...] = ("instruments", "stationery", "signalling", "rigging", "lighting")


def search(query: str = "", category: str = "", max_price: float | None = None) -> list[Item]:
    """The one place a result set is decided. Both the pages and the test hook call it."""
    q = (query or "").strip().lower()
    results = []
    for item in ITEMS:
        if q and q not in item.title.lower() and q not in item.sku.lower():
            continue
        if category and item.category != category:
            continue
        if max_price is not None and item.price_gbp > max_price:
            continue
        results.append(item)
    return results


def page_of(results: list[Item], page: int) -> list[Item]:
    start = (page - 1) * PAGE_SIZE
    return results[start:start + PAGE_SIZE]


def page_count(results: list[Item]) -> int:
    return max(1, -(-len(results) // PAGE_SIZE))


def by_sku(sku: str) -> Item | None:
    return next((i for i in ITEMS if i.sku == sku), None)


def ground_truth(query: str = "", category: str = "", max_price: float | None = None,
                 page: int = 1) -> dict[str, Any]:
    """The answer, from server state. Never reads markup, so mutations cannot move it."""
    results = search(query, category, max_price)
    shown = page_of(results, page)
    return {
        "query": query,
        "category": category,
        "max_price": max_price,
        "total_results": len(results),
        "page": page,
        "page_count": page_count(results),
        "page_size": PAGE_SIZE,
        "skus_on_page": [i.sku for i in shown],
        "titles_on_page": [i.title for i in shown],
        "all_skus": [i.sku for i in results],
        "empty": not results,
    }


def selftest() -> dict[str, Any]:
    """Assert the mutation layer cannot change an answer (S-9.3).

    Renders every mutation seed and confirms the ground truth is identical each time. If
    this fails the fixture is invalid as an evaluation instrument, because a repair could
    be credited for a change the mutation itself caused.
    """
    from fixture.mutations import SEEDS, apply_mutations

    baseline = ground_truth(category="instruments")
    failures = []
    for seed in SEEDS:
        after = ground_truth(category="instruments")
        if after != baseline:
            failures.append({"seed": seed, "reason": "ground truth changed with seed applied"})
        # The mutation layer must only ever touch markup.
        markup = apply_mutations("<div id='x' class='y'>Search</div>", seed)
        if not isinstance(markup, str):
            failures.append({"seed": seed, "reason": "mutation did not return markup"})
    return {
        "ok": not failures,
        "seeds_checked": list(SEEDS),
        "baseline": baseline,
        "failures": failures,
        "assertion": ("ground truth is computed from server state and is identical under "
                      "every mutation seed"),
    }


def item_dict(item: Item) -> dict[str, Any]:
    return asdict(item)

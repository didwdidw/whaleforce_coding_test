"""Pin the exact page version behind every OP-4…OP-7 target.

Wikipedia articles change, S&P 500 constituents get replaced, GDP figures are revised. Once
a dev case's expected answer is recorded without saying *which version of the page it came
from*, the case starts going red for reasons nobody can attribute: did the site change, or
did we get worse? Those need different responses, and by the time the question is asked the
evidence is gone.

So every target records the version identifier its own site offers:

- **Wikipedia** exposes `wgCurRevisionId` in the page's JS config, and a revision id is a
  permanent handle — `?oldid=<id>` renders exactly what we saw.
- **books.toscrape** is static with no version concept, so the honest substitute is a
  SHA-256 of the fetched bytes plus the retrieval timestamp: it cannot tell us what changed,
  but it can tell us *that* something did.

Retrieval goes through the same `ServerFetcher` the product uses, so robots and the egress
guard apply here exactly as they do to a run (A10.5).

Usage:  python -m preflight.pin_versions
"""

from __future__ import annotations

import json
import pathlib
import re
import time
from typing import Any

from app.fetcher import FetchRefused, ServerFetcher

OUT = pathlib.Path(__file__).parent.parent / "eval" / "target-versions.json"

REVISION = re.compile(rb'"wgCurRevisionId"\s*:\s*(\d+)')
PAGE_NAME = re.compile(rb'"wgPageName"\s*:\s*"([^"]+)"')
TIMESTAMP = re.compile(rb'"wgRevisionTimestamp"\s*:\s*"([^"]+)"')

TARGETS: dict[str, dict[str, str]] = {
    "OP-4": {
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "operation": "sort a sortable wikitable by a named column, read the top row",
        "why_this_page": "several sortable tables with overlapping header text, and the "
                         "constituent list changes often enough to matter",
    },
    "OP-5": {
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "operation": "expand a collapsed section or navbox and read a value from it",
        "why_this_page": "carries collapsible navboxes; S-3.4's fallback applies if none "
                         "is stable",
    },
    "OP-6": {
        "url": "https://books.toscrape.com/catalogue/category/books/nonfiction_13/index.html",
        "operation": "navigate to a category, page through the listing, extract list facts",
        "why_this_page": "multi-page category with the site's own result counter as a "
                         "coverage anchor",
    },
    "OP-7": {
        "url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "operation": "open a product detail page and extract a labelled field",
        "why_this_page": "a labelled product-information table, which is what label→value "
                         "binding is verified against",
    },
}


def version_of(body: bytes, url: str) -> dict[str, Any]:
    """The strongest version handle the site itself offers."""
    revision = REVISION.search(body)
    if revision:
        rev = revision.group(1).decode()
        page = PAGE_NAME.search(body)
        stamp = TIMESTAMP.search(body)
        return {
            "kind": "mediawiki_revision",
            "revision_id": rev,
            "page_name": page.group(1).decode() if page else None,
            "revision_timestamp": stamp.group(1).decode() if stamp else None,
            # Renders exactly what we saw, permanently.
            "permalink": f"{url.split('/wiki/')[0]}/w/index.php?oldid={rev}",
        }
    return {
        "kind": "content_hash",
        "note": ("This site publishes no version identifier. A hash cannot say what "
                 "changed, only that something did — which is still the difference "
                 "between 'the site moved' and 'we got worse'."),
    }


def main() -> None:
    fetcher = ServerFetcher()
    records = []
    for op, target in TARGETS.items():
        row: dict[str, Any] = {"operation_id": op, **target}
        try:
            result = fetcher.fetch(target["url"])
        except FetchRefused as exc:
            row["error"] = {"reason": exc.reason, "failure_class": exc.failure_class}
            records.append(row)
            print(f"{op:5} REFUSED  {exc.reason[:80]}")
            continue
        row.update({
            "final_url": result.final_url,
            "http_status": result.status,
            "retrieved_at": result.retrieved_at,
            "retrieved_on": time.strftime("%Y-%m-%d %H:%M:%SZ",
                                          time.gmtime(result.retrieved_at)),
            "sha256": result.sha256,
            "length": result.length,
            "robots": result.robots.to_dict(),
            "version": version_of(result.body, target["url"]),
        })
        records.append(row)
        version = row["version"]
        handle = version.get("revision_id") or result.sha256[:16]
        print(f"{op:5} {result.status}  {version['kind']:20} {handle}  "
              f"{result.length:>8} bytes")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "pinned_at": time.time(),
        "pinned_on": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
        "note": ("The page version each OP-4…OP-7 expected answer was taken from. When a "
                 "case starts failing, compare against this first: a changed revision id "
                 "or content hash means the site moved, and that is a different problem "
                 "from a regression."),
        "targets": records,
    }, indent=1), encoding="utf-8")
    print(f"\nwritten {OUT}")


if __name__ == "__main__":
    main()

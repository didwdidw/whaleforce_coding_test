"""Independent ground truth, where we can actually derive it (A25.4, A-76).

The dev set declared oracles — *"the harness fetches the table independently, applies the
same sort key, compares"* — and none of them existed. What the harness did was re-hash the
stored artifact and re-locate claimed values inside it: a real independent check of the
*evidence*, and not a derivation of the *right answer*. On OP-4 and OP-5, whose claimed
values are structures rather than strings, that left `independently_checked` at zero — so
S-10.10's "verified-but-wrong = 0" was unfalsifiable on the two records §4 calls
structurally shortcut-proof. Of the five broken-instrument defects in this project, it is
the only one whose direction was optimistic, which is why it survived longest.

This module derives the answer for **OP-4**, which is the one that is short and the one
whose trap is worth catching. Sorting a Wikipedia table by a column is a different result
depending on whether the column sorts numerically or lexicographically — `1000` before `99`
or after — and a run that sorts one way while the oracle sorts the other disagrees loudly
instead of agreeing plausibly.

**It fetches the page itself.** Not the stored artifact: an oracle reading the same bytes
the run stored would agree with the run about a page that had changed, which is exactly the
agreement worth nothing. The cost is that a live-page fetch can disagree because the site
changed between the run and the check, and that is reported as `not_comparable` rather than
as a failure — a disagreement we cannot attribute is not evidence against the run.
"""

from __future__ import annotations

import re
import urllib.request
from typing import Any

from eval.http_client import classify, ssl_context

ORACLE_VERSION = "oracle/1.0"
USER_AGENT = "WhaleforceCodingTest-Task1-oracle/1.0 (contact: didwdidw0309@gmail.com)"
#: Values that mean "no value" in a table cell, so a column of them does not read as numeric.
_BLANK = {"", "—", "–", "-", "n/a", "na", "none"}


def fetch(url: str, *, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=ssl_context()) as response:
            return response.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - a client-side failure is not a result
        classify(exc)
        raise


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def _number(value: str) -> float | None:
    """The numeric reading of a cell, or None if it has none.

    Wikipedia writes numbers with thousands separators, currency, footnote markers and
    ranges. Anything this cannot read as a single number is not a number, which is what
    keeps a mostly-numeric column from being sorted numerically on a guess.
    """
    cleaned = re.sub(r"\[[^\]]*\]", "", value or "")
    cleaned = cleaned.replace(",", "").replace("−", "-")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if match is None:
        return None
    # A cell that is a number *and* other things (a date range, "12 of 30") is not a number
    # for sorting purposes.
    remainder = cleaned.replace(match.group(0), "", 1)
    if re.search(r"\d", remainder):
        return None
    return float(match.group(0))


def sort_key_kind(values: list[str]) -> str:
    """`numeric` only when every non-blank cell reads as one. This is the distinction the
    case exists for: the same column sorted the other way is a different top row, and both
    orderings look completely reasonable on the page."""
    present = [v for v in values if _norm(v).lower() not in _BLANK]
    if present and all(_number(v) is not None for v in present):
        return "numeric"
    return "lexicographic"


def _tables(doc):
    return doc.xpath("//table[contains(@class,'wikitable')]")


def expected_top_row(url: str, column: str, direction: str, *,
                     html: str | None = None) -> dict[str, Any]:
    """The row that sorting `column` in `direction` puts at the top, derived from the page.

    Returns the derivation, not just the answer: the table it used, the sort key it chose
    and why, and how many rows it considered. A ground truth nobody can audit is another
    assertion.
    """
    from lxml import html as lxml_html

    try:
        source = html if html is not None else fetch(url)
    except Exception as exc:  # noqa: BLE001
        return {"oracle": ORACLE_VERSION, "available": False,
                "why": f"the page could not be fetched independently: {type(exc).__name__}"}

    doc = lxml_html.fromstring(source)
    wanted = _norm(column).lower()
    for index, table in enumerate(_tables(doc)):
        header_cells = table.xpath(".//tr[th][1]/th")
        headers = [_norm(th.text_content()) for th in header_cells]
        lowered = [h.lower() for h in headers]
        if wanted not in lowered:
            continue
        position = lowered.index(wanted)
        rows: list[list[str]] = []
        for tr in table.xpath(".//tr"):
            cells = tr.xpath("./td|./th")
            if len(cells) <= position or tr.xpath("./th") and not tr.xpath("./td"):
                continue
            rows.append([_norm(c.text_content()) for c in cells])
        if not rows:
            continue
        values = [r[position] for r in rows]
        kind = sort_key_kind(values)
        if kind == "numeric":
            def key(row: list[str]) -> Any:
                return _number(row[position]) if _number(row[position]) is not None else 0.0
        else:
            def key(row: list[str]) -> Any:
                return row[position].casefold()
        ordered = sorted(rows, key=key, reverse=direction == "descending")
        return {"oracle": ORACLE_VERSION, "available": True, "table_index": index,
                "headers": headers, "column": column, "column_index": position,
                "direction": direction, "sort_key": kind,
                "rows_considered": len(rows), "expected_top_row": ordered[0],
                "expected_top_value": ordered[0][position]}
    return {"oracle": ORACLE_VERSION, "available": False,
            "why": f"no wikitable on the page has a {column!r} column"}


def agrees_with(oracle: dict[str, Any], reported: Any) -> dict[str, Any]:
    """Whether what the run reported is the row the oracle derived.

    Compared cell by cell against the reported row's *values*, whatever shape the run
    reported them in, because the run reports each cell bound to its column header and the
    oracle reports a list. A run that reported a subset of the columns is checked on the
    cells it reported and said to have been checked on those.
    """
    if not oracle.get("available"):
        return {"comparable": False, "why": oracle.get("why", "no oracle")}
    expected = [_norm(c).lower() for c in oracle["expected_top_row"]]
    if isinstance(reported, dict):
        claimed = [_norm(str(v)).lower() for v in reported.values()]
    elif isinstance(reported, (list, tuple)):
        claimed = [_norm(str(v)).lower() for v in reported]
    else:
        claimed = [_norm(str(reported)).lower()]
    claimed = [c for c in claimed if c]
    if not claimed:
        return {"comparable": False, "why": "the run reported no row to compare"}
    missing = [c for c in claimed if c not in expected]
    return {"comparable": True, "agrees": not missing,
            "cells_compared": len(claimed), "not_in_expected_row": missing[:5],
            "expected_top_row": oracle["expected_top_row"],
            "sort_key": oracle["sort_key"]}

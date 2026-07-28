"""The one place a money figure is stated (A26 review, B-4).

Three documents each carried their own total, all three went stale on the same day, and one
of them — "total provider spend across every scored round" — was false rather than merely
old. A figure repeated in three places is three figures.

So it is generated. `docs/spend-ledger.md` is written from committed measurements: the
ledger readings in `eval/results/spend-readings.json` and the spend snapshot each round's
result file already carried in its provenance. The README and the analysis report point
here and state no total of their own.

Round costs come from those snapshots by subtraction, because the snapshot is taken **at the
start** of a split: the difference between one split's opening balance and the next one's is
what the first split spent. That is visible in the data (r1's dev split opens at 4 calls) and
it is the reason a round's cost is reported as a delta rather than as a field nobody wrote.

    python -m eval.spend_ledger            # rewrite docs/spend-ledger.md
    python -m eval.spend_ledger --check    # fail if it is out of date
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
READINGS = ROOT / "eval" / "results" / "spend-readings.json"
OUTPUT = ROOT / "docs" / "spend-ledger.md"

#: Ceilings are declared once in app/config.py; they are quoted here, not redefined.
from app.config import (  # noqa: E402
    CUMULATIVE_DEVELOPMENT_CEILING_USD as CUMULATIVE_DEV_CEILING_USD,
    SYSTEM_SPEND_CEILING_USD_PER_DAY,
)  # noqa: E402

#: What the owner's real limit is. The ceiling sits below it on purpose (A23.4).
OWNER_LIMIT_USD = 10.0

#: The order splits were scored in. A round's cost is the gap to the next opening balance.
SPLIT_ORDER = ("dev", "experimental", "validation", "test")


def readings() -> dict[str, Any]:
    return json.loads(READINGS.read_text(encoding="utf-8"))


def _opening(provenance: dict[str, Any]) -> tuple[float, int] | None:
    """The billed balance a split opened with, across both ledger schemas."""
    spend = provenance.get("spend") or {}
    if not spend:
        return None
    usd = spend.get("cumulative_billed_usd", spend.get("cumulative_usd"))
    calls = spend.get("cumulative_billed_calls", spend.get("cumulative_calls"))
    return (float(usd), int(calls)) if usd is not None else None


def scored_splits() -> list[dict[str, Any]]:
    """Every committed round result that carries an opening balance, in scoring order."""
    out = []
    for path in sorted((ROOT / "eval" / "results").glob("*-deploy-*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        provenance = report.get("provenance") or {}
        opening = _opening(provenance)
        if opening is None:
            continue
        started = provenance.get("started_at") or ""
        out.append({"file": path.name, "split": provenance.get("split", "?"),
                    "round": provenance.get("eval_round", path.stem.rsplit("-r", 1)[-1]),
                    "git_sha": (provenance.get("git_sha") or "")[:12],
                    "started_at": started,
                    "opening_usd": opening[0], "opening_calls": opening[1]})
    return sorted(out, key=lambda row: row["opening_usd"])


def billed_now(data: dict[str, Any]) -> tuple[float, int]:
    total, calls = 0.0, 0
    for reading in data["readings"]:
        for row in reading["rows"]:
            if row["tier"] != "free":
                total += row["usd"]
                calls += row["calls"]
    return round(total, 6), calls


def notional_now(data: dict[str, Any]) -> tuple[float, int]:
    total, calls = 0.0, 0
    for reading in data["readings"]:
        for row in reading["rows"]:
            if row["tier"] == "free":
                total += row["usd"]
                calls += row["calls"]
    return round(total, 6), calls


def render() -> str:
    data = readings()
    billed, billed_calls = billed_now(data)
    notional, notional_calls = notional_now(data)
    splits = scored_splits()

    lines = [
        "# Provider spend — the ledger",
        "",
        "**Generated. Do not edit by hand** — `python -m eval.spend_ledger` rewrites it from",
        "`eval/results/spend-readings.json` and the provenance blocks of the committed round",
        "results. It is the only place in this repository that states a spend total; the README",
        "and the analysis report link here rather than each carrying a number that goes stale",
        "on a different day.",
        "",
        "## Where it stands",
        "",
        "| | USD | Calls |",
        "|---|---|---|",
        f"| **Billed — money actually charged** | **{billed:.4f}** | {billed_calls} |",
        f"| Notional — free-tier calls priced at the same published rates, never charged "
        f"| {notional:.4f} | {notional_calls} |",
        "",
        f"Against a cumulative development ceiling of **USD {CUMULATIVE_DEV_CEILING_USD:.2f}** "
        f"(a hard stop), a system ceiling of **USD {SYSTEM_SPEND_CEILING_USD_PER_DAY:.2f}/day** "
        f"split between the scored workload and the public app, and the owner's real limit of "
        f"**USD {OWNER_LIMIT_USD:.2f}**.",
        "",
        "Only billed dollars are enforced against (A23.1). Notional is a price, not a charge;",
        "enforcing against the sum of the two is how the public demo came to be on course for a",
        "`provider_quota` after spending nothing.",
        "",
        "## By service",
        "",
        "| Service | Day | Tier | USD | Calls |",
        "|---|---|---|---|---|",
    ]
    for reading in data["readings"]:
        for row in reading["rows"]:
            lines.append(f"| {reading['service']} | {row['day']} | {row['tier']} | "
                         f"{row['usd']:.6f} | {row['calls']} |")
    lines += ["", "Readings taken by hand and recorded with their source:", ""]
    for reading in data["readings"]:
        lines.append(f"- **{reading['service']}**, {reading['taken_at']} — {reading['read_from']}")

    lines += [
        "",
        "## By split",
        "",
        "Each split's provenance records the balance it **opened** with, so a split's cost is",
        "the gap to the next opening balance. The last split's cost is the gap to the reading",
        "above, which also contains anything spent since — startup credential validations, and",
        "the part of a split that was interrupted before it could write a result.",
        "",
        "| Split | Round | Build | Opened at (USD / calls) | Cost of this split |",
        "|---|---|---|---|---|",
    ]
    for index, row in enumerate(splits):
        following = (splits[index + 1]["opening_usd"] if index + 1 < len(splits)
                     else billed)
        cost = round(following - row["opening_usd"], 6)
        tail = "" if index + 1 < len(splits) else " *(plus everything since)*"
        lines.append(f"| {row['split']} | r{row['round']} | `{row['git_sha']}` | "
                     f"{row['opening_usd']:.6f} / {row['opening_calls']} | "
                     f"**{cost:.4f}**{tail} |")

    lines += ["", "## Not in these numbers", ""]
    lines += [f"- {note}" for note in data.get("unledgered", ())]
    lines += [
        "",
        "## Updating it",
        "",
        "After a round: read the scored service's `provider_spend` table off its volume, append",
        "the reading to `eval/results/spend-readings.json`, and re-run the generator. `--check`",
        "fails if the committed document is out of date, so a stale total is a test failure",
        "rather than something a reader finds.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the committed document is out of date")
    args = parser.parse_args(argv)
    rendered = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(f"{OUTPUT} is out of date — run `python -m eval.spend_ledger`",
                  file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

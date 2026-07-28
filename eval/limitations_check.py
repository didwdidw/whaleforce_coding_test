"""Run every published limitation against the deployment and report what actually happens.

A25.1, and it was found the expensive way. `L-1` told a reader that naming the article
makes the task succeed; the title was assembled from the sentence without stripping the
trailing noun, the run navigated to `/wiki/List_of_S%26P_500_companies_article`, and it
ended `unsupported / postcondition_unmet`. An independent reviewer reproduced that in
thirty seconds.

**A limitation that cannot be reproduced as written is worse than no limitation.** The list
is this project's honesty surface, so an entry a reader can falsify converts the strongest
asset into evidence against it. The rule that follows is that the list is executable:

    python -m eval.limitations_check --base-url https://<host>

Both halves of an entry are run — the task, and the remedy phrasing where one is claimed —
because the remedy is part of what the entry says. The report is written to
`eval/results/limitations-<sha>.json` and is what A-73 is satisfied by.

This spends provider quota: the entries are real tasks on real sites. It is the cheapest
honest way to know, and the alternative is publishing prose about a system nobody ran.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from typing import Any

from app.limitations import LIMITATIONS
from eval.harness import Deployment

CHECK_VERSION = "limitations-check/1.0"
REPO = pathlib.Path(__file__).parent.parent


def _observe(deployment: Deployment, task: str, deadline: float) -> dict[str, Any]:
    submitted = deployment.submit(task)
    run_id = submitted.get("id") or submitted.get("run_id")
    if not run_id:
        # A refusal at admission is a terminal outcome, not a missing run.
        return {"terminal_status": submitted.get("terminal_status"),
                "failure_class": submitted.get("failure_class"),
                "explanation": submitted.get("explanation", ""), "run_id": None}
    run = deployment.await_run(run_id, deadline)
    return {"terminal_status": run.get("terminal_status"),
            "failure_class": run.get("failure_class"),
            "explanation": (run.get("explanation") or "")[:400],
            "run_id": run_id, "timed_out": bool(run.get("harness_timeout"))}


def _compare(expected_status: str, expected_class: str | None,
             seen: dict[str, Any]) -> tuple[bool, str]:
    if seen.get("timed_out"):
        return False, "the run did not reach a terminal status inside the deadline"
    if seen.get("terminal_status") != expected_status:
        return False, (f"published {expected_status!r}, observed "
                       f"{seen.get('terminal_status')!r}")
    # The failure class is compared only when the entry names one. An entry that names a
    # status and no class is making the narrower claim, and holding it to the wider one
    # would report a false discrepancy.
    if expected_class and seen.get("failure_class") != expected_class:
        return False, (f"published failure_class {expected_class!r}, observed "
                       f"{seen.get('failure_class')!r}")
    return True, ""


def run(base_url: str, *, deadline: float, only: str = "") -> dict[str, Any]:
    deployment = Deployment(base_url)
    health = deployment.json("/healthz")
    sha = (health.get("build") or {}).get("git_sha") or health.get("git_sha") or "unknown"
    entries = [limit for limit in LIMITATIONS if not only or limit.id == only]

    results: list[dict[str, Any]] = []
    for limit in entries:
        print(f"[{CHECK_VERSION}] {limit.id}: {limit.task[:70]}…", flush=True)
        seen = _observe(deployment, limit.task, deadline)
        reproduces, why = _compare(limit.outcome, limit.failure_class, seen)
        record: dict[str, Any] = {"id": limit.id, "task": limit.task,
                                  "published": {"terminal_status": limit.outcome,
                                                "failure_class": limit.failure_class},
                                  "observed": seen, "reproduces": reproduces,
                                  "discrepancy": why}
        if limit.remedy_task:
            print(f"[{CHECK_VERSION}] {limit.id} remedy: {limit.remedy_task[:60]}…",
                  flush=True)
            remedy_seen = _observe(deployment, limit.remedy_task, deadline)
            remedy_ok, remedy_why = _compare(limit.remedy_outcome, None, remedy_seen)
            record["remedy"] = {"task": limit.remedy_task,
                                "published": limit.remedy_outcome,
                                "observed": remedy_seen, "reproduces": remedy_ok,
                                "discrepancy": remedy_why}
            record["reproduces"] = record["reproduces"] and remedy_ok
        results.append(record)
        print(f"[{CHECK_VERSION}] {limit.id}: "
              f"{'reproduces' if record['reproduces'] else 'DOES NOT REPRODUCE — ' + (record['discrepancy'] or (record.get('remedy') or {}).get('discrepancy', ''))}",
              flush=True)

    failing = [r["id"] for r in results if not r["reproduces"]]
    return {"tool": CHECK_VERSION, "base_url": base_url, "git_sha": sha,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "entries": len(results), "reproduce": len(results) - len(failing),
            "do_not_reproduce": failing, "results": results,
            "note": ("A-73. Every published limitation is executed against the deployed "
                     "system before it is published and again before submission. An entry "
                     "listed in `do_not_reproduce` is a defect in the list, not a caveat "
                     "about it.")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--deadline", type=float, default=300.0,
                        help="seconds to wait for one run to reach a terminal status")
    parser.add_argument("--only", default="", help="check a single entry, e.g. L-1")
    parser.add_argument("--out", default="", help="where to write the report")
    args = parser.parse_args()

    report = run(args.base_url, deadline=args.deadline, only=args.only)
    out = pathlib.Path(args.out) if args.out else (
        REPO / "eval" / "results" / f"limitations-{report['git_sha'][:12]}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("entries", "reproduce", "do_not_reproduce")}, indent=1))
    print(f"[{CHECK_VERSION}] written {out}")
    return 0 if not report["do_not_reproduce"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

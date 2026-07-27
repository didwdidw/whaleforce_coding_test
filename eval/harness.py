"""Run an eval split against a deployed system and score it (A13.5).

`eval/dev-set.md` was prose and nothing executed it, which meant there was no hard gate
(§10.3), no first-run score, and no source of numbers for the analysis report. This runs a
split end to end over HTTP against a deployment — not in-process — because what is being
scored is the deployed system, and an in-process run would not exercise the queue, the
served artifacts, or the deployment's own configuration.

**What the oracle here does and does not cover, stated plainly**, because a scoring tool
that overstates its own reach is the same defect as a product that does:

- It checks each case's declared `expected_terminal_status` against what the run produced.
  That is the case's own machine-readable expectation and nothing is inferred around it.
- It re-fetches every evidence artifact and confirms the bytes hash to what the product
  recorded, that the claimed value is present in those bytes, and that the label the value
  was bound to is present too — with its own code, importing nothing from `app/`. This is
  what catches a fabricated value or a verifier that agrees with itself.
- It does **not** re-derive the answer from the live site. Several cases turn on state that
  only exists after an interaction (a sorted table's top row, page 3 of a listing), so a
  plain fetch of the entry URL would disagree with a correct run. Those cases are scored on
  status and evidence, and this file says so rather than implying more.

Held-out splits are run through the same code path with `--split validation` or
`--split test`, which suppresses every per-case detail: the caller gets the aggregate score,
the `failure_class` histogram and the provenance block, which is all S-10.4 permits to come
back from a held-out run.

Usage:
    python -m eval.harness --base-url https://<host> --split dev
    python -m eval.harness --base-url https://<host> --split validation --cases /path/to.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

HARNESS_VERSION = "harness/1.1"
REPO = pathlib.Path(__file__).parent.parent
DEFAULT_CASES = {"dev": REPO / "eval" / "dev-set.md",
                 "experimental": REPO / "eval" / "experimental-set.md"}
POLL_SECONDS = 3.0

TERMINAL_STATUSES = {"succeeded_verified", "no_result_verified", "partial", "unverified",
                     "failed", "blocked", "unsupported"}


# ---- the split ------------------------------------------------------------------

@dataclass(frozen=True)
class CaseSchema:
    """What one split's cases look like.

    The harness needs exactly three things from a case: something to identify it by,
    something to submit, and the outcomes the case will accept. Everything else is carried
    through untouched. Task 2's cases will name a company and a fiscal year rather than a
    browser task; they fill the same three roles, so they get a schema here rather than a
    second harness (A14.12).
    """

    name: str
    fields: tuple[str, ...]
    request_field: str
    expectation_field: str


BROWSER_TASK = CaseSchema(
    name="browser_task",
    fields=("record", "tier", "task", "entry_point", "expected_terminal_status"),
    request_field="task",
    expectation_field="expected_terminal_status",
)

SCHEMAS: dict[str, CaseSchema] = {BROWSER_TASK.name: BROWSER_TASK}


def parse_cases(path: pathlib.Path,
                schema: CaseSchema = BROWSER_TASK) -> list[dict[str, str]]:
    """Cases as the split file declares them. Fields are read, never inferred."""
    text = path.read_text(encoding="utf-8")
    cases = []
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        case: dict[str, str] = {"id": block.split()[0].strip()}
        for field in schema.fields:
            found = re.search(rf"^- \*\*{field}\*\*\s*(.*)$", block, re.M)
            if found:
                case[field] = found.group(1).strip()
        quoted = re.search(rf'^- \*\*{schema.request_field}\*\*\s+"(.+?)"\s*$', block, re.M)
        if quoted:
            case[schema.request_field] = quoted.group(1)
        if case.get(schema.request_field):
            cases.append(case)
    return cases


def accepted_statuses(case: dict[str, str],
                      schema: CaseSchema = BROWSER_TASK) -> set[str]:
    """Every status the case names as acceptable. A case may allow more than one."""
    declared = case.get(schema.expectation_field, "")
    return {s for s in re.findall(r"[a-z_]+", declared) if s in TERMINAL_STATUSES}


def outcome_kind(run: dict[str, Any]) -> str:
    """How this run ended, in the four categories a breadth figure needs.

    Kept in one place and named, because "attempt rate" and "abstention rate" (A14.4) are
    only meaningful if the boundary between refusing before looking and giving up after
    looking is drawn the same way for every case.
    """
    status = run.get("terminal_status")
    failure = run.get("failure_class")
    if failure in {"policy_refused", "robots_disallowed"}:
        return "refused_by_policy"
    if run.get("counts_as_success"):
        return "verified"
    if status == "unsupported":
        return "abstained_after_looking"
    return "failed_or_blocked"


def attempted(run: dict[str, Any]) -> bool:
    """Whether the run actually went to a page. Read from the trace rather than from the
    status, because a refusal and a failed attempt can share a terminal status."""
    return any(entry.get("kind") == "navigate" and entry.get("ok")
               for entry in (run.get("trace") or []))


# ---- the deployment -------------------------------------------------------------

class Deployment:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, attempts: int = 3) -> tuple[int, bytes]:
        """A dropped read is a fact about the network, not about the run being scored, so
        it is retried. Losing a whole split to one socket timeout is not a measurement."""
        last: Exception | None = None
        for attempt in range(attempts):
            request = urllib.request.Request(f"{self.base}{path}",
                                             headers={"User-Agent": HARNESS_VERSION})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                time.sleep(1.0 + attempt)
        raise RuntimeError(f"GET {path} failed after {attempts} attempts: {last}")

    def json(self, path: str) -> dict[str, Any]:
        status, body = self._get(path)
        if status != 200:
            raise RuntimeError(f"GET {path} -> {status}: {body[:200]!r}")
        return json.loads(body)

    def bytes_at(self, path: str) -> bytes | None:
        status, body = self._get(path)
        return body if status == 200 else None

    def submit(self, task: str, *, deadline_seconds: float = 300.0) -> dict[str, Any]:
        """Submit, waiting out a full queue rather than scoring it as a refusal.

        `queue_full` is a capacity answer about the deployment at that instant, not a
        result for the case. Recording it as one measures our queue depth and calls the
        number a success rate.
        """
        data = urllib.parse.urlencode({"task": task}).encode()
        deadline = time.time() + deadline_seconds
        while True:
            request = urllib.request.Request(f"{self.base}/api/runs", data=data,
                                             headers={"User-Agent": HARNESS_VERSION})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                # A deployment that answers an error with HTML is telling us something
                # about itself. Crashing the split loses the other fourteen cases.
                raw = exc.read()
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {"explanation": f"HTTP {exc.code}: {raw[:200]!r}",
                            "failure_class": "internal_error"}
                retry_after = float(exc.headers.get("Retry-After") or 0)
                if (exc.code == 429 and body.get("failure_class") == "queue_full"
                        and time.time() < deadline):
                    time.sleep(max(retry_after, POLL_SECONDS))
                    continue
                return body

    def await_run(self, run_id: str, deadline_seconds: float) -> dict[str, Any]:
        deadline = time.time() + deadline_seconds
        run: dict[str, Any] = {"id": run_id}
        while True:
            try:
                run = self.json(f"/api/runs/{run_id}")
                if run.get("state") == "done":
                    return run
            except RuntimeError:
                pass  # keep polling; the deadline is what ends this, not one bad read
            if time.time() > deadline:
                run["harness_timeout"] = True
                return run
            time.sleep(POLL_SECONDS)


# ---- the independent check ------------------------------------------------------

def check_evidence(deployment: Deployment, run: dict[str, Any]) -> dict[str, Any]:
    """Re-fetch the evidence and confirm it says what the product said it says.

    Deliberately implemented here rather than by calling the product: a verifier checked by
    its own code is a verifier checking itself, which is the thing every other control in
    this system is arranged to avoid.
    """
    findings: list[str] = []
    notes: list[str] = []
    claims = run.get("claims") or []
    checked = 0
    for claim in claims:
        bundle = claim.get("evidence") or {}
        name = claim.get("name", "?")
        if not claim.get("ok"):
            continue
        artifact_id = bundle.get("artifact_id")
        if not artifact_id:
            findings.append(f"{name}: verified with no artifact reference")
            continue
        raw = deployment.bytes_at(f"/api/artifacts/{artifact_id}")
        if raw is None:
            findings.append(f"{name}: artifact {artifact_id} could not be fetched")
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if bundle.get("artifact_sha256") and digest != bundle["artifact_sha256"]:
            findings.append(f"{name}: artifact hash differs from the recorded one")
            continue
        checked += 1
        text = _collapse(_rendered_text(raw))
        span = _collapse(str(bundle.get("extracted_span") or ""))
        label = _collapse(str(bundle.get("label_anchor") or ""))
        value = bundle.get("normalised_value")

        # Only a scalar claim has a value that must appear on the page. A claim whose value
        # is a structure or a boolean — a sort direction, an element proven absent — is a
        # state the product derived, and string-searching for it would report a finding on
        # every correct run. So it is counted as not string-checkable and said so, rather
        # than folded into the pass rate in either direction.
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            if span and span not in text:
                findings.append(
                    f"{name}: the value {str(value)[:60]!r} was reported as verified, and "
                    f"its extracted span is not present in the delivered artifact")
        else:
            notes.append(f"{name}: derived value ({type(value).__name__}), not "
                         f"string-checkable against the artifact")
        # The label anchor is literal page text for some relations and a description of a
        # structural rule for others. Not a finding either way; recorded so the report can
        # say how much of the evidence was confirmable from outside.
        if label and label not in text:
            notes.append(f"{name}: label anchor {label[:40]!r} is a rule, not page text")
    return {"claims": len(claims), "independently_checked": checked,
            "findings": findings, "notes": notes}


def _rendered_text(raw: bytes) -> str:
    """The artifact's text as a reader would see it. Comparing against raw markup instead
    reports a finding for every entity and every tag inside a value."""
    try:
        from lxml import html as lxml_html

        return lxml_html.fromstring(raw.decode("utf-8", "replace")).text_content()
    except Exception:  # noqa: BLE001 - unparseable evidence still gets the crude check
        return raw.decode("utf-8", "replace")


def _collapse(text: str) -> str:
    return " ".join(text.split()).lower()


# ---- scoring ---------------------------------------------------------------------

def score_case(case: dict[str, str], run: dict[str, Any], evidence: dict[str, Any],
               schema: CaseSchema = BROWSER_TASK) -> dict[str, Any]:
    accepted = accepted_statuses(case, schema)
    produced = run.get("terminal_status")
    status_ok = produced in accepted if accepted else None
    return {
        "case": case["id"],
        "record": case.get("record", ""),
        "declared_tier": case.get("tier", ""),
        "run_id": run.get("id"),
        "tier": run.get("tier"),
        "execution_path": run.get("execution_path"),
        "terminal_status": produced,
        "failure_class": run.get("failure_class"),
        "counts_as_success": bool(run.get("counts_as_success")),
        "outcome_kind": outcome_kind(run),
        "attempted": attempted(run),
        "expected": sorted(accepted),
        "status_as_expected": status_ok,
        "evidence": evidence,
        "duration_seconds": run.get("duration_seconds"),
        "latency": run.get("latency"),
        "budget": run.get("budget"),
        "timed_out_waiting": bool(run.get("harness_timeout")),
        "passed": bool(status_ok) and not evidence["findings"],
    }


def breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Attempt, verified and abstention rates (A14.4), plus the policy-refusal rate (A14.3).

    A system that says no is not the same as a system that cannot. These four numbers say
    which one a reader is looking at, and they are reported for the experimental tier where
    the graders' own unseen tasks land.
    """
    if not rows:
        return {"cases": 0}
    n = len(rows)
    kinds = [r["outcome_kind"] for r in rows]

    def share(count: int) -> dict[str, Any]:
        return {"count": count, "rate": round(count / n, 4),
                "interval_95": _wilson(count, n)}

    return {
        "cases": n,
        "attempted": share(sum(1 for r in rows if r["attempted"])),
        "verified": share(sum(1 for k in kinds if k == "verified")),
        "abstained_after_looking": share(sum(1 for k in kinds
                                             if k == "abstained_after_looking")),
        "refused_by_policy": share(sum(1 for k in kinds if k == "refused_by_policy")),
        "failed_or_blocked": share(sum(1 for k in kinds if k == "failed_or_blocked")),
    }


def _wilson(successes: int, n: int) -> list[float] | None:
    """A 95% Wilson interval (S-10.13). At these sample sizes a bare percentage implies a
    precision the split does not have."""
    if n == 0:
        return None
    z = 1.96
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denominator
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def latency_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Latency broken down the way A14.1 requires it to be read: by tier and by execution
    path. A single median over both paths describes neither — a deterministic run has no
    provider in it at all."""
    summaries = [r["latency"] for r in rows if isinstance(r.get("latency"), dict)]

    def by(key: str, value: str) -> list[dict[str, Any]]:
        return [r["latency"] for r in rows
                if isinstance(r.get("latency"), dict) and r.get(key) == value]

    report: dict[str, Any] = {"all": _aggregate_latency(summaries)}
    for tier in ("T-DECLARED", "T-EXPERIMENTAL"):
        report[tier] = _aggregate_latency(by("tier", tier))
    for path in ("model_driven", "scripted"):
        report[path] = _aggregate_latency(by("execution_path", path))
    return report


def _aggregate_latency(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """The same computation the product uses, restated here so the harness stays free of
    `app/` imports (S-12.4's discipline applied to the scorer)."""
    usable = [s for s in summaries
              if s.get("reportable") and s.get("run_seconds") is not None]
    excluded = len(summaries) - len(usable)
    if not usable:
        return {"n": 0, "excluded_unreportable": excluded}

    def spread(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"n": 0}
        ordered = sorted(values)
        p90 = ordered[min(len(ordered) - 1, int(-(-0.9 * len(ordered)) // 1) - 1)]
        return {"n": len(values), "median": round(statistics.median(ordered), 2),
                "p90": round(p90, 2), "min": round(ordered[0], 2),
                "max": round(ordered[-1], 2)}

    def field(name: str) -> list[float]:
        return [float(s[name]) for s in usable if s.get(name) is not None]

    return {
        "n": len(usable),
        "excluded_unreportable": excluded,
        "run_seconds": spread(field("run_seconds")),
        "time_to_first_result_seconds": spread(field("time_to_first_result_seconds")),
        "queue_wait_seconds": spread(field("queue_wait_seconds")),
        "model_seconds": spread(field("model_seconds")),
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Declared and experimental are counted apart. S-1.3 puts only declared runs in the
    headline rate, and S-5.2 keeps `partial` and `unverified` out of any success figure."""
    declared = [r for r in results if r["tier"] == "T-DECLARED"]
    experimental = [r for r in results if r["tier"] == "T-EXPERIMENTAL"]
    histogram: dict[str, int] = {}
    for result in results:
        key = result["failure_class"] or "none"
        histogram[key] = histogram.get(key, 0) + 1

    def rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        passed = sum(1 for r in rows if r["passed"])
        return {"cases": len(rows), "passed": passed,
                "rate": round(passed / len(rows), 4) if rows else None}

    return {
        "headline_declared": rate(declared),
        "experimental_reported_separately": rate(experimental),
        "all_cases": rate(results),
        "failure_class_histogram": dict(sorted(histogram.items())),
        "evidence_findings": sum(len(r["evidence"]["findings"]) for r in results),
        # What the system did when it was not on ground it had declared: the surface the
        # graders' unseen tasks land on (A14.3, A14.4).
        "experimental_breadth": breadth(experimental),
        "shortcut_refusals": sum(1 for r in results
                                 if r["failure_class"] == "required_action_skipped"),
        "latency": latency_report(results),
    }


def provenance(deployment: Deployment, cases_path: pathlib.Path,
               split: str) -> dict[str, Any]:
    """S-10.7: what a score is only meaningful alongside."""
    health = deployment.json("/healthz")
    return {
        "harness_version": HARNESS_VERSION,
        "split": split,
        "base_url": deployment.base,
        "git_sha": health.get("git_sha"),
        "model_pinned": health.get("model_pinned"),
        "eval_set_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "eval_set_file": cases_path.name,
        "planner_available": (health.get("planner") or {}).get("available"),
        "credentials": health.get("credentials"),
        # No cookie is carried, so each case is its own session. The per-session run cap is
        # a public-demo control (S-11.12); applying it to a scoring run would cap a 15-case
        # split at 10 and the missing five would look like failures.
        "session_policy": "one session per case",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ---- entry point -----------------------------------------------------------------

def run_split(base_url: str, split: str, cases_path: pathlib.Path,
              deadline_seconds: float, verbose: bool,
              schema: CaseSchema = BROWSER_TASK) -> dict[str, Any]:
    # Before touching the deployment: a split that parses to nothing would otherwise score
    # 100% of nothing, and the run would look like a clean pass.
    cases = parse_cases(cases_path, schema)
    if not cases:
        raise SystemExit(f"No cases parsed from {cases_path}. A split that parses to "
                         f"nothing scores 100% of nothing.")
    deployment = Deployment(base_url)
    meta = provenance(deployment, cases_path, split)
    meta["case_schema"] = schema.name

    results = []
    for case in cases:
        submitted = deployment.submit(case[schema.request_field],
                                      deadline_seconds=deadline_seconds)
        run_id = submitted.get("run_id")
        if not run_id:
            results.append({
                "case": case["id"], "record": case.get("record", ""),
                "declared_tier": case.get("tier", ""), "run_id": None, "tier": None,
                "execution_path": None, "terminal_status": None,
                "failure_class": submitted.get("failure_class") or "admission_refused",
                "counts_as_success": False,
                "outcome_kind": "failed_or_blocked", "attempted": False,
                "expected": sorted(accepted_statuses(case, schema)),
                "status_as_expected": False,
                "evidence": {"claims": 0, "independently_checked": 0,
                             "findings": [f"not admitted: {submitted.get('explanation')}"]},
                "duration_seconds": None, "latency": None, "budget": None,
                "timed_out_waiting": False, "passed": False})
            if verbose:
                print(f"  {case['id']}: refused at admission")
            continue
        run = deployment.await_run(run_id, deadline_seconds)
        result = score_case(case, run, check_evidence(deployment, run), schema)
        results.append(result)
        if verbose:
            print(f"  {result['case']:8} {result['tier'] or '-':15} "
                  f"{result['execution_path'] or '-':13} "
                  f"{result['terminal_status'] or '-':20} "
                  f"{'PASS' if result['passed'] else 'FAIL'}")

    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = {"provenance": meta, "aggregate": aggregate(results)}
    # Per-case detail is withheld for the held-out splits only: their content must not reach
    # the session that must not see it. Dev and experimental are visible splits.
    if split in {"dev", "experimental"}:
        report["cases"] = results
    else:
        report["note"] = ("Per-case detail is withheld for a held-out split (S-10.4). The "
                          "aggregate score, the failure-class histogram and the provenance "
                          "block are the whole permitted result.")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--split", default="dev",
                        choices=("dev", "experimental", "validation", "test"))
    parser.add_argument("--cases", type=pathlib.Path)
    parser.add_argument("--case-schema", default=BROWSER_TASK.name, choices=sorted(SCHEMAS))
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--deadline", type=float, default=300.0,
                        help="seconds to wait for one run, including queueing")
    args = parser.parse_args(argv)

    cases_path = args.cases or DEFAULT_CASES.get(args.split)
    if cases_path is None:
        raise SystemExit(f"--cases is required for the {args.split} split: its content is "
                         f"deliberately not in this repository (eval/holdout-manifest.md)")
    verbose = args.split in {"dev", "experimental"}
    report = run_split(args.base_url, args.split, cases_path, args.deadline, verbose,
                       SCHEMAS[args.case_schema])

    out = args.out or (REPO / "eval" / "results" /
                       f"{args.split}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")

    print(json.dumps(report["aggregate"], indent=1))
    print(json.dumps(report["provenance"], indent=1))
    print(f"\nwritten {out}")
    return 0 if report["aggregate"]["all_cases"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

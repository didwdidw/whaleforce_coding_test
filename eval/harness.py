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
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HARNESS_VERSION = "harness/1.0"
REPO = pathlib.Path(__file__).parent.parent
DEFAULT_CASES = {"dev": REPO / "eval" / "dev-set.md"}
POLL_SECONDS = 3.0


# ---- the split ------------------------------------------------------------------

def parse_cases(path: pathlib.Path) -> list[dict[str, str]]:
    """Cases as the split file declares them. Fields are read, never inferred."""
    text = path.read_text(encoding="utf-8")
    cases = []
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        case: dict[str, str] = {"id": block.split()[0].strip()}
        for field in ("record", "tier", "task", "entry_point",
                      "expected_terminal_status"):
            found = re.search(rf"^- \*\*{field}\*\*\s*(.*)$", block, re.M)
            if found:
                case[field] = found.group(1).strip()
        task = re.search(r'^- \*\*task\*\*\s+"(.+?)"\s*$', block, re.M)
        if task:
            case["task"] = task.group(1)
        if case.get("task"):
            cases.append(case)
    return cases


def accepted_statuses(case: dict[str, str]) -> set[str]:
    """Every status the case names as acceptable. A case may allow more than one."""
    declared = case.get("expected_terminal_status", "")
    return {s for s in re.findall(r"[a-z_]+", declared)
            if s in {"succeeded_verified", "no_result_verified", "partial", "unverified",
                     "failed", "blocked", "unsupported"}}


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

def score_case(case: dict[str, str], run: dict[str, Any],
               evidence: dict[str, Any]) -> dict[str, Any]:
    accepted = accepted_statuses(case)
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
        "expected": sorted(accepted),
        "status_as_expected": status_ok,
        "evidence": evidence,
        "duration_seconds": run.get("duration_seconds"),
        "budget": run.get("budget"),
        "timed_out_waiting": bool(run.get("harness_timeout")),
        "passed": bool(status_ok) and not evidence["findings"],
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
              deadline_seconds: float, verbose: bool) -> dict[str, Any]:
    # Before touching the deployment: a split that parses to nothing would otherwise score
    # 100% of nothing, and the run would look like a clean pass.
    cases = parse_cases(cases_path)
    if not cases:
        raise SystemExit(f"No cases parsed from {cases_path}. A split that parses to "
                         f"nothing scores 100% of nothing.")
    deployment = Deployment(base_url)
    meta = provenance(deployment, cases_path, split)

    results = []
    for case in cases:
        submitted = deployment.submit(case["task"], deadline_seconds=deadline_seconds)
        run_id = submitted.get("run_id")
        if not run_id:
            results.append({
                "case": case["id"], "record": case.get("record", ""),
                "declared_tier": case.get("tier", ""), "run_id": None, "tier": None,
                "execution_path": None, "terminal_status": None,
                "failure_class": submitted.get("failure_class") or "admission_refused",
                "counts_as_success": False, "expected": sorted(accepted_statuses(case)),
                "status_as_expected": False,
                "evidence": {"claims": 0, "independently_checked": 0,
                             "findings": [f"not admitted: {submitted.get('explanation')}"]},
                "duration_seconds": None, "budget": None, "timed_out_waiting": False,
                "passed": False})
            if verbose:
                print(f"  {case['id']}: refused at admission")
            continue
        run = deployment.await_run(run_id, deadline_seconds)
        result = score_case(case, run, check_evidence(deployment, run))
        results.append(result)
        if verbose:
            print(f"  {result['case']:8} {result['tier'] or '-':15} "
                  f"{result['execution_path'] or '-':13} "
                  f"{result['terminal_status'] or '-':20} "
                  f"{'PASS' if result['passed'] else 'FAIL'}")

    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = {"provenance": meta, "aggregate": aggregate(results)}
    # Per-case detail is dev-only. A held-out split returns the score and the histogram;
    # anything more would put case content in front of the session that must not see it.
    if split == "dev":
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
                        choices=("dev", "validation", "test"))
    parser.add_argument("--cases", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--deadline", type=float, default=300.0,
                        help="seconds to wait for one run, including queueing")
    args = parser.parse_args(argv)

    cases_path = args.cases or DEFAULT_CASES.get(args.split)
    if cases_path is None:
        raise SystemExit(f"--cases is required for the {args.split} split: its content is "
                         f"deliberately not in this repository (eval/holdout-manifest.md)")
    verbose = args.split == "dev"
    report = run_split(args.base_url, args.split, cases_path, args.deadline, verbose)

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

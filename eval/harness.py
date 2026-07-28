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
- For **OP-4** it re-derives the answer: it fetches the article itself, finds the table
  carrying the named column, decides numerically-vs-lexicographically from that column's own
  values, sorts and compares the top row. That is the one check here that can say a
  *verified* run is wrong about the world rather than about its own evidence.
- For everything else it does **not** re-derive the answer, and says so per case. Several
  cases turn on state that only exists after an interaction (an expanded box, page 3 of a
  listing), so a plain fetch of the entry URL would disagree with a correct run. Those cases
  are scored on status and evidence, and the split's `oracle` field names which kind of
  check each one gets — until Amendment 25 every case claimed a derivation and every case
  got a re-check, which left "verified-but-wrong = 0" unfalsifiable on our strongest records.

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

from eval.http_client import classify, ssl_context

HARNESS_VERSION = "harness/1.3"
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
    #: Fields without which a case cannot be scored honestly. Missing one is an error in
    #: the split, raised before the deployment is touched.
    required_fields: tuple[str, ...] = ()


BROWSER_TASK = CaseSchema(
    name="browser_task",
    fields=("record", "tier", "task", "entry_point", "expected_terminal_status"),
    request_field="task",
    expectation_field="expected_terminal_status",
    required_fields=("tier", "entry_point", "expected_terminal_status"),
)

SCHEMAS: dict[str, CaseSchema] = {BROWSER_TASK.name: BROWSER_TASK}

def field_value(block: str, field: str, fields: tuple[str, ...]) -> str | None:
    """One declared field, wherever on its line it was written.

    `dev-set.md` writes `- **record** OP-4 · **tier** T-DECLARED`, and a line-anchored
    pattern parsed `tier` as empty for every case in the split — so the only tier in the
    results was the one each run reported about itself, and two readings that exist to be
    compared silently became one (A17.5).

    A value ends at the next *field* marker, not at the next bold text. DEV-15 writes
    ``succeeded_verified` **or** `unsupported``, and cutting at any `**`
    would drop two of the three statuses that case accepts.
    """
    found = re.search(rf"\*\*{field}\*\*[ \t]*(.*)$", block, re.M)
    if not found:
        return None
    value = found.group(1)
    others = "|".join(re.escape(f) for f in fields if f != field)
    cut = re.search(rf"\*\*(?:{others})\*\*", value) if others else None
    if cut:
        value = value[:cut.start()]
    return value.strip().rstrip("·").strip()


def parse_cases(path: pathlib.Path,
                schema: CaseSchema = BROWSER_TASK) -> list[dict[str, str]]:
    """Cases as the split file declares them. Fields are read, never inferred."""
    text = path.read_text(encoding="utf-8")
    cases = []
    # `##` or `###`: the two splits head their cases at different levels, and a parser tied
    # to one of them reads the other as a file with no cases in it.
    for block in re.split(r"^#{2,3} ", text, flags=re.M)[1:]:
        case: dict[str, str] = {"id": block.split()[0].strip()}
        for field in schema.fields:
            value = field_value(block, field, schema.fields)
            if value is not None:
                case[field] = value
        quoted = re.search(rf'\*\*{schema.request_field}\*\*\s+"(.+?)"\s*$', block, re.M)
        if quoted:
            case[schema.request_field] = quoted.group(1)
        if case.get(schema.request_field):
            cases.append(case)
    return cases


def check_schema(cases: list[dict[str, str]], schema: CaseSchema = BROWSER_TASK) -> None:
    """Refuse to score a split whose cases do not declare what scoring needs (A17.5).

    Loud, and before the deployment is touched. A field the parser cannot see is a field
    that silently reads as empty, and an empty declaration compared against a run's
    self-report agrees with everything.
    """
    missing = [f"{case['id']}: {field}" for case in cases
               for field in schema.required_fields if not case.get(field)]
    if missing:
        raise SystemExit(
            f"{len(missing)} case field(s) missing or unparsed in this split: "
            + ", ".join(missing[:10])
            + ". Either the file does not declare them or the parser cannot see them; "
              "both make the score describe something other than the split.")


def accepted_statuses(case: dict[str, str],
                      schema: CaseSchema = BROWSER_TASK) -> set[str]:
    """Every status the case names as acceptable. A case may allow more than one."""
    declared = case.get(schema.expectation_field, "")
    return {s for s in re.findall(r"[a-z_]+", declared) if s in TERMINAL_STATUSES}


#: `| `ALIAS` | `https://…` |` in a split's targets table. Cases name their entry point by
#: alias, and an alias nothing resolves is an entry point nobody can check.
ALIAS_ROW = re.compile(r"^\|\s*`([A-Z0-9_]+)`\s*\|\s*`([^`]+)`", re.M)


def aliases(path: pathlib.Path) -> dict[str, str]:
    """The split's own targets table, with its abbreviations expanded.

    A targets table writes the first URL for a site in full and abbreviates the rest —
    ``.../catalogue/category/books/poetry_23/index.html``. Reading only absolute rows left
    most cases with no resolvable entry point, which is a precondition silently not checked:
    the same shape as the defect the precondition exists to catch.
    """
    resolved: dict[str, str] = {}
    origin = ""
    for name, value in ALIAS_ROW.findall(path.read_text(encoding="utf-8")):
        if value.startswith("http"):
            origin = "://".join(urllib.parse.urlsplit(value)[:2])
            resolved[name] = value
        elif origin:
            resolved[name] = origin + "/" + value.lstrip(". /")
    return resolved


def entry_url(case: dict[str, str], alias_map: dict[str, str]) -> str | None:
    """The URL this case says it starts at, or None when it declares no reachable one.

    None is a real answer: a case that is *about* being refused before browsing ("would
    require /wiki/Special:Search", "none") has no entry point to probe, and inventing one
    would assert a precondition the case never made.
    """
    declared = (case.get("entry_point") or "").strip().strip("`").strip()
    if declared.startswith("http"):
        return declared
    return alias_map.get(declared)


def precondition(deployment: "Deployment", url: str | None) -> dict[str, Any]:
    """Whether the system under test can reach this case's declared entry point (A17.4).

    Asked before the case is submitted, because the alternative is what happened: the
    fixture was not running, the egress guard refused the request, and the suite recorded a
    policy refusal and moved on — for a milestone. The defect that hid behind it was not
    merely present, it was invisible by construction.
    """
    if url is None:
        return {"url": None, "checked": False, "ok": True,
                "reason": "the case declares no reachable entry point, so there is "
                          "nothing to assert before running it"}
    try:
        probe = deployment.json(f"/api/reachability?url={urllib.parse.quote(url, safe='')}")
    except RuntimeError as exc:
        return {"url": url, "checked": True, "ok": False,
                "reason": f"the deployment could not answer a reachability probe: {exc}"}
    # A path the site's own robots.txt closes is a live site answering for itself, which is
    # a precondition met — several cases target exactly that on purpose.
    ok = bool(probe.get("reachable")) or bool(probe.get("origin_up"))
    return {"url": url, "checked": True, "ok": ok, "reason": probe.get("reason"),
            "http_status": probe.get("http_status"), "robots": probe.get("robots")}


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
                with urllib.request.urlopen(request, timeout=self.timeout,
                                            context=ssl_context()) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                # A failure on this machine is not a fact about the deployment: an
                # unverifiable certificate here would otherwise retry three times and
                # report the site as unreachable, for every case in the split.
                classify(exc)
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
                with urllib.request.urlopen(request, timeout=self.timeout,
                                            context=ssl_context()) as response:
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
    not_reproducible: list[str] = []
    claims = run.get("claims") or []
    verified = [c for c in claims if c.get("ok")]
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
                # The only case where this scorer has independently re-located the value.
                # Confirming the artifact's hash says the bytes are the ones recorded; it
                # says nothing about the claim, and counting it as a check on the claim is
                # a count of checks that did not happen (A17.6).
                checked += 1
        elif isinstance(value, list) and value and all(
                isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
            # An enumeration is re-derivable member by member, which is most of what a
            # list-level claim asserts. Counting it as unreachable would understate what an
            # outside check can actually confirm, and it is the claim absence rests on.
            absent = [str(v) for v in value if _collapse(str(v)) not in text]
            if absent:
                findings.append(
                    f"{name}: {len(absent)} enumerated member(s) reported as verified are "
                    f"not present in the delivered artifact: {', '.join(absent[:5])}")
            else:
                checked += 1
        else:
            not_reproducible.append(
                f"{name}: derived value ({type(value).__name__}), which this scorer cannot "
                f"re-derive from the artifact by string comparison")
        # The label anchor is literal page text for some relations and a description of a
        # structural rule for others. Not a finding either way; recorded so the report can
        # say how much of the evidence was confirmable from outside.
        if label and label not in text:
            notes.append(f"{name}: label anchor {label[:40]!r} is a rule, not page text")
    return {"claims": len(claims), "verified_claims": len(verified),
            "independently_checked": checked,
            # Named, not folded away: what this scorer could not re-derive is a limit of
            # the scorer, and a reader has to be able to see how much of a run's evidence
            # the outside check actually reached.
            "not_reproducible_here": not_reproducible,
            "findings": findings, "notes": notes}


#: Attributes a browser surfaces to a reader — a tooltip, an image's replacement text, an
#: accessible name, the ghost text in a field. Everything not listed here is markup.
VISIBLE_ATTRIBUTES = ("title", "alt", "aria-label", "placeholder")


def _rendered_text(raw: bytes) -> str:
    """What a reader can actually see in the artifact (A24.1): the rendered text plus the
    values of the attributes above.

    Neither end of this is arbitrary. Comparing against raw markup reports a finding for
    every entity and every tag inside a value, and lets a URL, a class name or a script
    literal satisfy a claim the artifact never delivered. Comparing against `text_content()`
    alone was the r1 defect: a site that truncates a long title in the text and carries the
    whole of it in `title=` made the product's better behaviour — reading the attribute —
    look like an unbacked claim.

    Script and style text is stripped rather than left in: it is the one place a value can
    sit that no reader ever sees.
    """
    try:
        from lxml import etree, html as lxml_html

        doc = lxml_html.fromstring(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - unparseable evidence still gets the crude check
        return raw.decode("utf-8", "replace")
    etree.strip_elements(doc, "script", "style", etree.Comment, with_tail=False)
    parts = [doc.text_content()]
    for node in doc.iter():
        get = getattr(node, "get", None)
        if get is None:
            continue
        parts.extend(value for value in (get(a) for a in VISIBLE_ATTRIBUTES) if value)
    return " ".join(parts)


def _collapse(text: str) -> str:
    return " ".join(text.split()).lower()


# ---- scoring ---------------------------------------------------------------------

def independent_oracle(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Derive the right answer independently, for the records where that is possible.

    Only OP-4 today, and the shape of the answer says so rather than implying more. For
    every other record the harness re-checks the *evidence* and not the *answer*, which is
    a real check and a narrower one — and saying which is which is the whole point of
    A25.4, because the dev set used to describe oracles that did not exist.
    """
    if case.get("record") != "OP-4":
        return {"kind": "evidence re-check only",
                "why": "no independent derivation of the answer exists for this record"}
    postcondition = run.get("postcondition") or {}
    inputs = postcondition.get("inputs") or {}
    url = postcondition.get("target_url") or ""
    column = str(inputs.get("sort_column") or "")
    direction = str(inputs.get("direction") or "")
    if not (url and column and direction):
        return {"kind": "op4", "comparable": False,
                "why": "the run froze no article, column and direction to check against"}
    claim = next((c for c in (run.get("claims") or []) if c.get("name") == "top_row"), None)
    if claim is None:
        return {"kind": "op4", "comparable": False,
                "why": "the run reported no top row"}
    reported = (claim.get("evidence") or {}).get("normalised_value")
    from eval.oracles import agrees_with, expected_top_row

    derived = expected_top_row(url, column, direction)
    return {"kind": "op4", "url": url, **agrees_with(derived, reported)}


def score_case(case: dict[str, str], run: dict[str, Any], evidence: dict[str, Any],
               schema: CaseSchema = BROWSER_TASK,
               pre: dict[str, Any] | None = None) -> dict[str, Any]:
    accepted = accepted_statuses(case, schema)
    produced = run.get("terminal_status")
    status_ok = produced in accepted if accepted else None
    declared_tier = case.get("tier", "")
    reported_tier = run.get("tier")
    # Two readings that exist to be compared. When they disagree that is a finding about
    # the case or about admission, and it is reported rather than resolved here (A17.5).
    tier_agrees = (None if not declared_tier or not reported_tier
                   else declared_tier == reported_tier)
    findings = list(evidence["findings"])
    if tier_agrees is False:
        findings.append(f"declared tier {declared_tier} but the run reports {reported_tier}")
    oracle = independent_oracle(case, run)
    if oracle.get("comparable") and oracle.get("agrees") is False:
        # The only check in this harness that can say a *verified* run is wrong about the
        # world rather than about its own evidence. A disagreement here is what makes
        # "verified-but-wrong = 0" falsifiable at all (A25.4).
        findings.append(
            f"the independent oracle sorted {oracle.get('sort_key')} and expects "
            f"{oracle.get('expected_top_row')}; the run reported cells not in that row: "
            f"{', '.join(oracle.get('not_in_expected_row') or [])}")
    evidence = {**evidence, "findings": findings}
    return {
        "case": case["id"],
        "record": case.get("record", ""),
        "declared_tier": declared_tier,
        "tier_as_declared": tier_agrees,
        "precondition": pre or {"checked": False, "ok": True},
        "suite_error": bool(pre and not pre.get("ok")),
        "run_id": run.get("id"),
        "tier": reported_tier,
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
        "oracle": oracle,
        "passed": bool(status_ok) and not evidence["findings"],
    }


def scorable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows that measure the product rather than the run of the suite.

    A case whose entry point could not be reached measures our test setup. Leaving it in
    any rate — as a pass, a refusal, or an abstention — reports a property of the suite as
    a property of the system (A17.4).
    """
    return [r for r in rows if not r.get("suite_error")]


def breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Attempt, verified and abstention rates (A14.4), plus the policy-refusal rate (A14.3).

    A system that says no is not the same as a system that cannot. These four numbers say
    which one a reader is looking at, and they are reported for the experimental tier where
    the graders' own unseen tasks land.
    """
    excluded = len(rows) - len(scorable(rows))
    rows = scorable(rows)
    if not rows:
        return {"cases": 0, "excluded_suite_errors": excluded}
    n = len(rows)
    kinds = [r["outcome_kind"] for r in rows]

    def share(count: int) -> dict[str, Any]:
        return {"count": count, "rate": round(count / n, 4),
                "interval_95": _wilson(count, n)}

    return {
        "cases": n,
        "excluded_suite_errors": excluded,
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
    errors = [r for r in results if r.get("suite_error")]
    counted = scorable(results)
    declared = [r for r in counted if r["tier"] == "T-DECLARED"]
    experimental = [r for r in counted if r["tier"] == "T-EXPERIMENTAL"]
    histogram: dict[str, int] = {}
    for result in counted:
        key = result["failure_class"] or "none"
        histogram[key] = histogram.get(key, 0) + 1

    def rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        passed = sum(1 for r in rows if r["passed"])
        return {"cases": len(rows), "passed": passed,
                "rate": round(passed / len(rows), 4) if rows else None}

    return {
        "headline_declared": rate(declared),
        "experimental_reported_separately": rate(experimental),
        "all_cases": rate(counted),
        # Not a score. A case whose entry point was unreachable says the suite did not run
        # properly, and it is reported as its own number rather than counted as anything.
        "suite_errors": {"cases": len(errors),
                         "detail": [{"case": r["case"],
                                     "reason": r["precondition"].get("reason")}
                                    for r in errors]},
        "failure_class_histogram": dict(sorted(histogram.items())),
        "evidence_findings": sum(len(r["evidence"]["findings"]) for r in counted),
        # Declared tier against the tier the run reported about itself (A17.5).
        "tier_disagreements": [{"case": r["case"], "declared": r["declared_tier"],
                                "reported": r["tier"]}
                               for r in counted if r.get("tier_as_declared") is False],
        # What the system did when it was not on ground it had declared: the surface the
        # graders' unseen tasks land on (A14.3, A14.4).
        "experimental_breadth": breadth(experimental),
        "shortcut_refusals": sum(1 for r in counted
                                 if r["failure_class"] == "required_action_skipped"),
        "latency": latency_report(counted),
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
        # A17.10: a cost or latency figure is only comparable against the caps it was
        # measured under, and those caps have already been relaxed once. Answering "which
        # cap was this?" from the commit history is reconstruction; the file should say.
        "budgets": health.get("budgets"),
        "prices_usd_per_1m": health.get("prices_usd_per_1m"),
        "spend": health.get("provider_spend"),
        # No cookie is carried, so each case is its own session. The per-session run cap is
        # a public-demo control (S-11.12); applying it to a scoring run would cap a 15-case
        # split at 10 and the missing five would look like failures.
        "session_policy": "one session per case",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def degradation(meta: dict[str, Any], results: list[dict[str, Any]],
                split: str) -> dict[str, Any] | None:
    """Whether the system was impaired while this split ran (A18.7).

    It goes inside the file, not in the filename and not in the directory's README: a
    filename gets copied off the number it qualifies and a README gets skipped, and the
    rule is that the qualifier travels with the number. A file carrying this block is not
    a capability measurement and must not be the source of a figure in the report.
    """
    reasons = []
    # Both classes say the model call did not happen for a reason on the provider's side.
    # Neither is a fact about the agent, and one of them used to be the other: a rate limit
    # was reported as `provider_error` until the tier cooldown landed.
    provider_side = [r["case"] for r in results
                     if r.get("failure_class") in ("provider_quota", "provider_error")]
    if provider_side:
        reasons.append(f"the provider refused or failed the call on "
                       f"{len(provider_side)} case(s) ({', '.join(provider_side)}): those "
                       f"cases measure the provider, not the system")
    if meta.get("planner_available") is False:
        reasons.append("the planner was unavailable, so every model-driven case was "
                       "decided by something other than the model")
    errors = [r["case"] for r in results if r.get("suite_error")]
    if errors:
        reasons.append(f"the suite could not run {len(errors)} case(s) "
                       f"({', '.join(errors)}): a precondition of the case failed")
    unfinished = [r["case"] for r in results if r.get("timed_out_waiting")]
    if unfinished:
        reasons.append(f"{len(unfinished)} case(s) were still running when the harness "
                       f"stopped waiting ({', '.join(unfinished)})")
    policy = (meta.get("credentials") or {}).get("policy")
    if split in ("validation", "test") and policy != "scored":
        reasons.append(f"a held-out split ran under credential policy {policy!r}, not "
                       f"'scored' (A9.6): it could have died of free-tier exhaustion")
    if not reasons:
        return None
    return {
        "not_a_capability_measurement": True,
        "reasons": reasons,
        "consequence": ("No figure in the analysis report may be sourced from this file. "
                        "It is kept because a degraded run is a real observation, and "
                        "deleting the inconvenient run is how a result set becomes a "
                        "highlight reel."),
    }


# ---- entry point -----------------------------------------------------------------

def _suite_error(case: dict[str, str], schema: CaseSchema,
                 pre: dict[str, Any]) -> dict[str, Any]:
    return {
        "case": case["id"], "record": case.get("record", ""),
        "declared_tier": case.get("tier", ""), "tier_as_declared": None,
        "precondition": pre, "suite_error": True,
        "run_id": None, "tier": None, "execution_path": None, "terminal_status": None,
        "failure_class": None, "counts_as_success": False,
        "outcome_kind": "suite_error", "attempted": False,
        "expected": sorted(accepted_statuses(case, schema)), "status_as_expected": None,
        "evidence": {"claims": 0, "verified_claims": 0, "independently_checked": 0,
                     "not_reproducible_here": [], "findings": [], "notes": []},
        "duration_seconds": None, "latency": None, "budget": None,
        "timed_out_waiting": False, "passed": False,
    }


def run_split(base_url: str, split: str, cases_path: pathlib.Path,
              deadline_seconds: float, verbose: bool,
              schema: CaseSchema = BROWSER_TASK) -> dict[str, Any]:
    # Before touching the deployment: a split that parses to nothing would otherwise score
    # 100% of nothing, and the run would look like a clean pass.
    cases = parse_cases(cases_path, schema)
    if not cases:
        raise SystemExit(f"No cases parsed from {cases_path}. A split that parses to "
                         f"nothing scores 100% of nothing.")
    check_schema(cases, schema)
    alias_map = aliases(cases_path)
    deployment = Deployment(base_url)
    meta = provenance(deployment, cases_path, split)
    meta["case_schema"] = schema.name

    results = []
    for case in cases:
        pre = precondition(deployment, entry_url(case, alias_map))
        if not pre["ok"]:
            # Not a result for the case. The suite itself did not run properly here, and
            # scoring it as a pass, a refusal or an abstention is how a real defect stayed
            # invisible for a milestone (A17.4).
            results.append(_suite_error(case, schema, pre))
            if verbose:
                print(f"  {case['id']:8} SUITE ERROR  {pre['reason']}")
            continue
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
                "evidence": {"claims": 0, "verified_claims": 0,
                             "independently_checked": 0, "not_reproducible_here": [],
                             "notes": [],
                             "findings": [f"not admitted: {submitted.get('explanation')}"]},
                "duration_seconds": None, "latency": None, "budget": None,
                "precondition": pre, "suite_error": False, "tier_as_declared": None,
                "timed_out_waiting": False, "passed": False})
            if verbose:
                print(f"  {case['id']}: refused at admission")
            continue
        run = deployment.await_run(run_id, deadline_seconds)
        result = score_case(case, run, check_evidence(deployment, run), schema, pre)
        results.append(result)
        if verbose:
            print(f"  {result['case']:8} {result['tier'] or '-':15} "
                  f"{result['execution_path'] or '-':13} "
                  f"{result['terminal_status'] or '-':20} "
                  f"{'PASS' if result['passed'] else 'FAIL'}")

    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    degraded = degradation(meta, results, split)
    if degraded:
        meta["degraded"] = degraded
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

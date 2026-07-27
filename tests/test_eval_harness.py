"""The harness that turns a split into a score (A13.5).

Two things are asserted here that matter more than the arithmetic. A split that parses to
nothing must not score 100% of nothing — the same vacuity the verifier fails closed on
(A11.7), one layer up, and the layer where nobody would notice. And a held-out split must
come back as a score, a histogram and provenance, with no case detail attached, because the
session that reads the result is the session that must not see the cases (S-10.4).
"""

from __future__ import annotations

import pathlib

import pytest

from eval.harness import (
    accepted_statuses, aggregate, check_evidence, parse_cases, score_case,
)

DEV_SET = pathlib.Path(__file__).parent.parent / "eval" / "dev-set.md"


def test_the_dev_split_parses_into_cases_with_tasks_and_expectations():
    cases = parse_cases(DEV_SET)
    assert len(cases) == 15
    assert all(c["task"] for c in cases)
    assert all(accepted_statuses(c) for c in cases)


def test_a_split_that_parses_to_nothing_is_an_error_not_a_perfect_score(tmp_path):
    from eval.harness import run_split

    empty = tmp_path / "empty.md"
    empty.write_text("# Nothing here\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        run_split("http://127.0.0.1:1", "dev", empty, 1.0, False)


def test_multiple_acceptable_statuses_are_all_accepted():
    """DEV-15 names three, and a harness that took the first would fail two correct
    outcomes of a case written to allow them."""
    cases = {c["id"]: c for c in parse_cases(DEV_SET)}
    assert accepted_statuses(cases["DEV-15"]) == {"succeeded_verified", "unsupported",
                                                  "blocked", "unverified"}
    assert accepted_statuses(cases["DEV-01"]) == {"succeeded_verified"}


# --- the independent check ---------------------------------------------------------

class _Deployment:
    """Serves whatever bytes the test wants under an artifact id."""

    base = "http://test"

    def __init__(self, artifacts: dict[str, bytes]) -> None:
        self._artifacts = artifacts

    def bytes_at(self, path: str) -> bytes | None:
        return self._artifacts.get(path.rsplit("/", 1)[-1])


def _run(value: str, span: str, label: str, artifact_id: str, sha: str) -> dict:
    return {"claims": [{"name": "upc", "ok": True, "evidence": {
        "artifact_id": artifact_id, "artifact_sha256": sha, "extracted_span": span,
        "label_anchor": label, "normalised_value": value}}]}


def test_evidence_that_backs_the_claim_passes():
    import hashlib

    body = b"<table><tr><th>UPC</th><td>a897fe39b1053632</td></tr></table>"
    sha = hashlib.sha256(body).hexdigest()
    result = check_evidence(_Deployment({"art1": body}),
                            _run("a897fe39b1053632", "a897fe39b1053632", "UPC", "art1", sha))
    assert result["findings"] == []
    assert result["independently_checked"] == 1


def test_a_value_that_is_not_in_the_artifact_is_reported():
    """The failure this exists for: a claim marked verified whose value the delivered
    evidence does not contain."""
    import hashlib

    body = b"<table><tr><th>UPC</th><td>somethingelse</td></tr></table>"
    sha = hashlib.sha256(body).hexdigest()
    result = check_evidence(_Deployment({"art1": body}),
                            _run("a897fe39b1053632", "a897fe39b1053632", "UPC", "art1", sha))
    assert any("extracted span" in f for f in result["findings"])


def test_a_tampered_artifact_is_reported():
    result = check_evidence(_Deployment({"art1": b"<html>anything</html>"}),
                            _run("x", "x", "UPC", "art1", "0" * 64))
    assert any("hash differs" in f for f in result["findings"])


def test_a_verified_claim_with_no_artifact_is_reported():
    run = {"claims": [{"name": "upc", "ok": True, "evidence": {}}]}
    result = check_evidence(_Deployment({}), run)
    assert any("no artifact reference" in f for f in result["findings"])


# --- scoring -----------------------------------------------------------------------

def _case(expected: str, tier: str = "T-DECLARED") -> dict:
    return {"id": "X-1", "record": "OP-4", "tier": tier,
            "expected_terminal_status": expected}


def _result(status: str, tier: str, passed_evidence: bool = True) -> dict:
    run = {"id": "run_1", "tier": tier, "terminal_status": status,
           "counts_as_success": status in ("succeeded_verified", "no_result_verified"),
           "execution_path": "model_driven"}
    evidence = {"claims": 1, "independently_checked": 1,
                "findings": [] if passed_evidence else ["value not in artifact"]}
    return score_case(_case("`succeeded_verified`", tier), run, evidence)


def test_a_case_fails_when_the_evidence_does_not_back_it_even_if_the_status_is_right():
    """A status is what the product says about itself. It is not evidence."""
    scored = _result("succeeded_verified", "T-DECLARED", passed_evidence=False)
    assert scored["status_as_expected"] and not scored["passed"]


def test_the_headline_rate_counts_declared_runs_only():
    """S-1.3. An experimental result carried into the headline figure is the same
    over-claim as a `partial` counted as success."""
    results = [_result("succeeded_verified", "T-DECLARED"),
               _result("failed", "T-DECLARED"),
               _result("succeeded_verified", "T-EXPERIMENTAL")]
    summary = aggregate(results)
    assert summary["headline_declared"] == {"cases": 2, "passed": 1, "rate": 0.5}
    assert summary["experimental_reported_separately"]["cases"] == 1
    assert summary["all_cases"]["cases"] == 3


def test_the_failure_histogram_covers_every_case():
    results = [_result("failed", "T-DECLARED"), _result("succeeded_verified", "T-DECLARED")]
    results[0]["failure_class"] = "verification_mismatch"
    summary = aggregate(results)
    assert sum(summary["failure_class_histogram"].values()) == len(results)


# --- what a held-out run is allowed to return --------------------------------------

def test_a_held_out_split_returns_no_case_detail(monkeypatch, tmp_path):
    """The engineering session reads this output. It must not be a way to read the cases."""
    import eval.harness as harness

    cases = tmp_path / "holdout.md"
    cases.write_text('### V-1\n- **task** "do a thing"\n'
                     "- **expected_terminal_status** `succeeded_verified`\n", encoding="utf-8")

    monkeypatch.setattr(harness, "provenance",
                        lambda *a, **k: {"harness_version": "test", "split": "validation"})
    monkeypatch.setattr(harness.Deployment, "submit",
                        lambda self, task, **kw: {"run_id": "run_1"})
    monkeypatch.setattr(harness.Deployment, "await_run",
                        lambda self, run_id, deadline: {
                            "id": run_id, "tier": "T-DECLARED", "claims": [],
                            "terminal_status": "succeeded_verified",
                            "counts_as_success": True})

    report = harness.run_split("http://test", "validation", cases, 1.0, False)
    assert set(report) == {"provenance", "aggregate", "note"}
    serialised = str(report)
    assert "do a thing" not in serialised and "V-1" not in serialised


# --- breadth: what the system did when it was off declared ground -------------------

def _run_json(status: str, failure: str | None = None, navigated: bool = True,
              tier: str = "T-EXPERIMENTAL") -> dict:
    return {"id": "run_1", "tier": tier, "terminal_status": status,
            "failure_class": failure, "execution_path": "model_driven",
            "counts_as_success": status in ("succeeded_verified", "no_result_verified"),
            "trace": [{"kind": "navigate", "ok": True}] if navigated else []}


@pytest.mark.parametrize("status,failure,expected", [
    ("unsupported", "policy_refused", "refused_by_policy"),
    ("blocked", "robots_disallowed", "refused_by_policy"),
    ("unsupported", "postcondition_unmet", "abstained_after_looking"),
    ("succeeded_verified", None, "verified"),
    ("no_result_verified", None, "verified"),
    ("failed", "verification_mismatch", "failed_or_blocked"),
    ("unverified", None, "failed_or_blocked"),
])
def test_refusing_before_looking_is_not_the_same_outcome_as_giving_up_after(
        status, failure, expected):
    """A14.3 and A14.4 both turn on this boundary. Collapsing them would let a system that
    never opens a browser report the same abstention rate as one that tries and stops."""
    from eval.harness import outcome_kind

    assert outcome_kind(_run_json(status, failure)) == expected


def test_a_success_status_is_never_read_as_a_refusal():
    """`policy_refused` is checked first, so a defect that set both would have hidden a
    success behind a refusal label. It cannot happen, and this is why."""
    from eval.harness import outcome_kind

    run = _run_json("succeeded_verified", None)
    assert outcome_kind(run) == "verified"


def test_attempt_is_read_from_the_trace_not_from_the_status():
    """A refusal and a failed attempt can share a terminal status; only the trace says
    whether a page was ever opened."""
    from eval.harness import attempted

    assert attempted(_run_json("failed", navigated=True))
    assert not attempted(_run_json("failed", navigated=False))


def test_breadth_reports_attempt_verified_and_abstention_with_an_interval():
    from eval.harness import breadth

    rows = [score_case(_case("`succeeded_verified`", "T-EXPERIMENTAL"),
                       _run_json("succeeded_verified"), _evidence()),
            score_case(_case("`unsupported`", "T-EXPERIMENTAL"),
                       _run_json("unsupported", "postcondition_unmet"), _evidence()),
            score_case(_case("`unsupported`", "T-EXPERIMENTAL"),
                       _run_json("unsupported", "policy_refused", navigated=False),
                       _evidence())]
    report = breadth(rows)
    assert report["cases"] == 3
    assert report["verified"]["count"] == 1
    assert report["abstained_after_looking"]["count"] == 1
    assert report["refused_by_policy"]["count"] == 1
    assert report["attempted"]["count"] == 2
    low, high = report["verified"]["interval_95"]
    assert low < report["verified"]["rate"] < high


def _evidence() -> dict:
    return {"claims": 0, "independently_checked": 0, "findings": []}


# --- latency reporting ---------------------------------------------------------------

def _latency(seconds: float, reportable: bool = True) -> dict:
    return {"run_seconds": seconds, "time_to_first_result_seconds": seconds / 2,
            "queue_wait_seconds": 0.5, "model_seconds": seconds / 4,
            "reportable": reportable}


def test_latency_is_reported_per_tier_and_per_path_not_only_pooled():
    """A pooled median describes neither path: a deterministic run has no provider in it."""
    from eval.harness import latency_report

    rows = [{"tier": "T-DECLARED", "execution_path": "model_driven",
             "latency": _latency(30.0)},
            {"tier": "T-EXPERIMENTAL", "execution_path": "scripted",
             "latency": _latency(6.0)}]
    report = latency_report(rows)
    assert report["all"]["n"] == 2
    assert report["T-DECLARED"]["run_seconds"]["median"] == 30.0
    assert report["scripted"]["run_seconds"]["median"] == 6.0
    assert report["model_driven"]["n"] == 1


def test_a_run_served_from_the_development_cache_is_kept_out_of_the_figures():
    from eval.harness import latency_report

    rows = [{"tier": "T-DECLARED", "execution_path": "model_driven",
             "latency": _latency(30.0)},
            {"tier": "T-DECLARED", "execution_path": "model_driven",
             "latency": _latency(0.4, reportable=False)}]
    report = latency_report(rows)
    assert report["all"]["n"] == 1
    assert report["all"]["excluded_unreportable"] == 1
    assert report["all"]["run_seconds"]["median"] == 30.0


# --- the case schema is pluggable (A14.12) -------------------------------------------

def test_a_split_with_different_fields_needs_a_schema_not_a_second_harness(tmp_path):
    """Task 2's cases name a company and a fiscal year. Same three roles — identify,
    submit, expect — so they parse here."""
    from eval.harness import CaseSchema, parse_cases as parse

    schema = CaseSchema(name="filing_lookup",
                        fields=("company", "fiscal_year", "request", "expected_status"),
                        request_field="request", expectation_field="expected_status")
    path = tmp_path / "filing-set.md"
    path.write_text('### Q2-1\n- **company** Apple Inc.\n- **fiscal_year** 2024\n'
                    '- **request** "the FY2024 10-K"\n'
                    '- **expected_status** `succeeded_verified`\n', encoding="utf-8")
    cases = parse(path, schema)
    assert cases == [{"id": "Q2-1", "company": "Apple Inc.", "fiscal_year": "2024",
                      "request": "the FY2024 10-K",
                      "expected_status": "`succeeded_verified`"}]
    assert accepted_statuses(cases[0], schema) == {"succeeded_verified"}

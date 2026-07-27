"""Latency is measured, not recomputed (A14.1).

Cost was already instrumented properly: tokens and USD are recorded when they are spent and
read back from the record. Latency was not — the run page's wall clock called `time.time()`
at render, so a stored run reported a duration that depended on when you looked at it. These
tests hold the two properties that makes the difference: a finished run's timings never move,
and a run whose model calls came from the development cache is excluded from every reported
figure rather than quietly making the median look good.
"""

from __future__ import annotations

import pathlib
import re
import time

import pytest

from app.latency import aggregate, first_result_at, summarise
from app.models import BudgetUse, Run, StepKind, Tier, TraceEntry

APP = pathlib.Path(__file__).parent.parent / "app"


def _run(**kwargs) -> Run:
    now = 1_000_000.0
    run = Run(id="r", task="t", tier=Tier.DECLARED, created_at=now,
              started_at=now + 2.0, finished_at=now + 12.0,
              budget=BudgetUse(started_at=now + 2.0, ended_at=now + 12.0))
    for key, value in kwargs.items():
        setattr(run, key, value)
    return run


def _entry(seq: int, kind: StepKind, start: float, end: float | None,
           **detail) -> TraceEntry:
    return TraceEntry(seq=seq, kind=kind, summary=f"step {seq}", started_at=start,
                      finished_at=end, detail=detail)


def _model_call(seq: int, start: float, end: float, seconds: float,
                cached: bool = False) -> TraceEntry:
    return _entry(seq, StepKind.NOTE, start, end, purpose="exploration",
                  proposal={"call": {"seconds": seconds, "cached": cached}})


# ---- the figure must not move ---------------------------------------------------

def test_a_finished_runs_wall_clock_does_not_grow_between_reads():
    run = _run()
    first = run.budget.to_dict()["elapsed_seconds"]
    time.sleep(0.01)
    assert run.budget.to_dict()["elapsed_seconds"] == first == 10.0


def test_a_running_run_still_reports_time_so_far():
    """The live figure is what the progress view needs; only the finished one is frozen."""
    budget = BudgetUse(started_at=time.time() - 5.0)
    assert 4.0 < budget.elapsed_seconds < 7.0


def test_every_place_a_run_ends_stamps_the_budget():
    """A terminus that forgets the stamp reintroduces the growing clock silently, and only
    on that one path. Cheaper to enumerate the assignments than to find that later."""
    missing = []
    for path in sorted(APP.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if re.search(r"^\s*run\.finished_at = time\.time\(\)\s*$", line):
                following = " ".join(lines[i + 1:i + 3])
                if "budget.ended_at" not in following:
                    missing.append(f"{path.name}:{i + 1}")
    assert not missing, f"run ends without stamping the budget at {missing}"


# ---- time to first result -------------------------------------------------------

def test_time_to_first_result_is_the_first_successful_extraction():
    run = _run(trace=[
        _entry(1, StepKind.NAVIGATE, 1_000_002.0, 1_000_004.0),
        _entry(2, StepKind.CLICK, 1_000_004.0, 1_000_005.0),
        _entry(3, StepKind.EXTRACT, 1_000_005.0, 1_000_007.5),
        _entry(4, StepKind.EXTRACT, 1_000_008.0, 1_000_009.0),
    ])
    assert summarise(run)["time_to_first_result_seconds"] == 5.5


def test_a_failed_extraction_is_not_a_first_result():
    entry = _entry(1, StepKind.EXTRACT, 1_000_002.0, 1_000_003.0)
    entry.ok = False
    assert first_result_at(_run(trace=[entry])) is None


def test_a_run_that_read_nothing_reports_no_first_result_rather_than_its_duration():
    """An abstention has no moment where a value existed. Letting the total stand in for one
    would put refusals into the time-to-answer distribution."""
    run = _run(trace=[_entry(1, StepKind.NAVIGATE, 1_000_002.0, 1_000_004.0)])
    summary = summarise(run)
    assert summary["time_to_first_result_seconds"] is None
    assert summary["run_seconds"] == 10.0


# ---- the cache must not flatter the numbers -------------------------------------

def test_a_cached_model_call_makes_the_whole_run_unreportable():
    run = _run(trace=[_model_call(1, 1_000_002.0, 1_000_002.1, 0.0, cached=True)])
    assert summarise(run)["reportable"] is False


def test_model_seconds_counts_only_calls_that_actually_went_to_the_provider():
    run = _run(trace=[_model_call(1, 1_000_002.0, 1_000_004.0, 1.8),
                      _model_call(2, 1_000_004.0, 1_000_004.1, 0.0, cached=True)])
    summary = summarise(run)
    assert summary["model_seconds"] == 1.8
    assert summary["model_calls"] == 2 and summary["model_calls_cached"] == 1


def test_an_unreportable_run_is_excluded_from_the_distribution_and_counted():
    reportable = summarise(_run(trace=[_model_call(1, 1_000_002.0, 1_000_004.0, 1.5)]))
    cached = summarise(_run(trace=[_model_call(1, 1_000_002.0, 1_000_002.1, 0.0,
                                               cached=True)]))
    report = aggregate([reportable, cached])
    assert report["n"] == 1 and report["excluded_unreportable"] == 1


def test_a_distribution_over_nothing_reportable_is_empty_not_zero():
    """Zero seconds is a claim about speed. No sample is a claim about the sample."""
    report = aggregate([summarise(_run(trace=[_model_call(1, 1_000_002.0, 1_000_002.1,
                                                          0.0, cached=True)]))])
    assert report["n"] == 0 and "run_seconds" not in report


# ---- per-step and queue ---------------------------------------------------------

def test_queue_wait_is_separated_from_execution():
    """A run that waited for a browser context was not slow; the deployment was busy. A14.2
    needs those apart to read queue wait under load at all."""
    summary = summarise(_run())
    assert summary["queue_wait_seconds"] == 2.0
    assert summary["run_seconds"] == 10.0
    assert summary["total_seconds"] == 12.0


def test_the_slowest_step_is_named():
    run = _run(trace=[_entry(1, StepKind.NAVIGATE, 1_000_002.0, 1_000_003.0),
                      _entry(2, StepKind.CLICK, 1_000_003.0, 1_000_009.0)])
    assert summarise(run)["slowest_step"]["seq"] == 2
    assert summarise(run)["slowest_step"]["ms"] == 6000


def test_a_step_that_never_finished_is_counted_rather_than_dropped_silently():
    run = _run(trace=[_entry(1, StepKind.NAVIGATE, 1_000_002.0, 1_000_003.0),
                      _entry(2, StepKind.CLICK, 1_000_003.0, None)])
    summary = summarise(run)
    assert summary["steps_measured"] == 1 and summary["steps_unmeasured"] == 1


@pytest.mark.parametrize("field", ["queue_wait_seconds", "run_seconds",
                                   "time_to_first_result_seconds", "model_seconds",
                                   "step_ms", "reportable"])
def test_the_run_record_carries_every_latency_field(field):
    """A14.1 requires these in the trace and the UI. The run's own dict is where both read
    them from, so a field dropped there disappears from everything at once."""
    assert field in _run().to_dict()["latency"]

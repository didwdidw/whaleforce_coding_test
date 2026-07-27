"""Wall-clock measurement for a run, instrumented the way cost is (A14.1).

Every figure here is read back from what the run recorded while it was running. Nothing is
recomputed against the current time, so a stored run reports the same latency a week later
as it did the moment it finished — the same property the cost figures already have, and the
reason a budget's `elapsed_seconds` alone was not usable for reporting.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from app.models import Run, StepKind, TraceEntry


def _duration(entry: TraceEntry) -> float | None:
    if entry.finished_at is None:
        return None
    return max(0.0, entry.finished_at - entry.started_at)


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank, which for the handful of steps in a run is the only honest reading —
    interpolation would invent a duration no step took."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def model_calls(run: Run) -> list[dict[str, Any]]:
    """The provider calls in this run and the seconds the provider itself took.

    Kept apart from step duration because it answers a different question: how much of a run
    is spent waiting on the model rather than on the browser. A cached call is marked —
    latency measured over a cache hit is not latency (A8.13).
    """
    calls: list[dict[str, Any]] = []
    for entry in run.trace:
        call = (entry.detail.get("proposal") or {}).get("call")
        if not isinstance(call, dict):
            continue
        calls.append({
            "seq": entry.seq,
            "purpose": entry.detail.get("purpose"),
            "seconds": float(call.get("seconds") or 0.0),
            "cached": bool(call.get("cached")),
        })
    return calls


def first_result_at(run: Run) -> float | None:
    """The moment the run first held a candidate answer: the first successful extraction.

    Before it the run has navigated but read nothing; after it there is a value a user could
    be shown. A run that never extracts — a refusal, an abstention, a blocked run — has no
    such moment and reports nothing, rather than letting its total duration stand in for one.
    """
    for entry in run.trace:
        if entry.kind is StepKind.EXTRACT and entry.ok and entry.finished_at is not None:
            return entry.finished_at
    return None


def summarise(run: Run) -> dict[str, Any]:
    measured = [(entry, d) for entry in run.trace
                if (d := _duration(entry)) is not None]
    seconds = [d for _, d in measured]
    calls = model_calls(run)
    live = [c for c in calls if not c["cached"]]
    slowest = max(measured, key=lambda pair: pair[1], default=None)
    first = first_result_at(run)

    return {
        "queue_wait_seconds": (None if run.started_at is None
                               else round(run.started_at - run.created_at, 3)),
        "run_seconds": (None if not (run.started_at and run.finished_at)
                        else round(run.finished_at - run.started_at, 3)),
        "total_seconds": (None if run.finished_at is None
                          else round(run.finished_at - run.created_at, 3)),
        "time_to_first_result_seconds": (
            None if first is None or run.started_at is None
            else round(first - run.started_at, 3)),
        "steps_measured": len(measured),
        "steps_unmeasured": len(run.trace) - len(measured),
        "step_ms": {
            "median": _ms(statistics.median(seconds)) if seconds else None,
            "p90": _ms(_percentile(seconds, 0.9)) if seconds else None,
            "max": _ms(max(seconds)) if seconds else None,
        },
        "slowest_step": (None if slowest is None else {
            "seq": slowest[0].seq,
            "kind": slowest[0].kind.value,
            "summary": slowest[0].summary,
            "ms": _ms(slowest[1]),
        }),
        "model_seconds": round(sum(c["seconds"] for c in live), 3),
        "model_calls": len(calls),
        "model_calls_cached": len(calls) - len(live),
        # Whether this run's timings may be reported. A cached model call makes a run faster
        # than it would ever be in front of a user, so one cache hit disqualifies the whole
        # run rather than just that call.
        "reportable": not any(c["cached"] for c in calls),
    }


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Distribution over a set of latency summaries, for the analysis report.

    Takes the summaries rather than the runs so the eval harness — which only ever sees a
    deployment's JSON — can use the same function as the server.
    """
    usable = [r for r in runs if r.get("reportable") and r.get("run_seconds") is not None]
    excluded = len(runs) - len(usable)
    if not usable:
        return {"n": 0, "excluded_unreportable": excluded}

    totals = [float(r["run_seconds"]) for r in usable]
    firsts = [float(r["time_to_first_result_seconds"]) for r in usable
              if r.get("time_to_first_result_seconds") is not None]
    waits = [float(r["queue_wait_seconds"]) for r in usable
             if r.get("queue_wait_seconds") is not None]
    model = [float(r["model_seconds"]) for r in usable]

    def spread(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"n": 0, "median": None, "p90": None, "min": None, "max": None}
        return {
            "n": len(values),
            "median": round(statistics.median(values), 2),
            "p90": round(_percentile(values, 0.9), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    return {
        "n": len(usable),
        "excluded_unreportable": excluded,
        "run_seconds": spread(totals),
        "time_to_first_result_seconds": spread(firsts),
        "queue_wait_seconds": spread(waits),
        "model_seconds": spread(model),
        # How much of a median run is the provider. The single most useful number for
        # deciding whether an optimisation belongs in the browser or in the prompt.
        "model_share_of_median_run": (
            None if not totals or statistics.median(totals) == 0
            else round(statistics.median(model) / statistics.median(totals), 3)),
        "runs_without_a_result": len(usable) - len(firsts),
    }

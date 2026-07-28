"""Measure what the deployment does under load (A14.2).

S-11.8 fixes concurrency 2 and queue depth 2. That is a decision, not a measurement: it says
what we configured, not what the service delivers, where it starts refusing, how long a run
waits behind others, or how long it takes to be able to answer at all after a restart. This
produces one honest number for each.

Two things about the load itself, because a throughput figure is worthless without them:

- **The load is fixture work on the deterministic path.** It exercises the queue, the browser
  pool, the store and the HTTP surface, and it calls no model. A load test built from
  model-driven runs would spend the free tier's daily allowance — the one resource in this
  project that cannot be bought back — to measure a number that is mostly provider latency
  anyway. The projection at the end converts the measured capacity into model-driven terms
  using the real per-run durations the eval harness recorded, and says that it did.
- **Saturation is measured by asking for more than the queue holds.** A 429 here is the
  system working; the number being measured is where it starts.

Usage:
    python -m eval.loadtest --base-url http://127.0.0.1:8080
    python -m eval.loadtest --base-url http://127.0.0.1:8080 --cold-start
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

REPO = pathlib.Path(__file__).parent.parent
LOADTEST_VERSION = "loadtest/1.0"

#: Fixture tasks: real browser work, no provider call. One is a proof-of-absence so the
#: load is not four copies of the same code path.
LOAD_TASKS: tuple[str, ...] = (
    "Search the fixture catalogue for lantern",
    "Read page 2 of the fixture browse listing without clicking next",
    "Is any product in the fixture catalogue priced over £100?",
)


# ---- HTTP ------------------------------------------------------------------------

def _submit(base: str, task: str, timeout: float = 60.0) -> dict[str, Any]:
    """One submission, with the queue's answer returned rather than retried. Retrying a 429
    here would erase the measurement."""
    data = urllib.parse.urlencode({"task": task}).encode()
    request = urllib.request.Request(f"{base}/api/runs", data=data,
                                     headers={"User-Agent": LOADTEST_VERSION})
    sent = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
            return {"http": response.status, "sent_at": sent, **body}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"explanation": raw[:200].decode("utf-8", "replace")}
        return {"http": exc.code, "sent_at": sent,
                "retry_after": exc.headers.get("Retry-After"), **body}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"http": None, "sent_at": sent, "error": str(exc)}


def _get_json(base: str, path: str, timeout: float = 30.0) -> dict[str, Any] | None:
    request = urllib.request.Request(f"{base}{path}",
                                     headers={"User-Agent": LOADTEST_VERSION})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except ValueError:
            return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _drain(base: str, run_ids: list[str], deadline_seconds: float,
           poll_seconds: float = 1.0) -> list[dict[str, Any]]:
    """Wait for every run to reach `done`, so the next burst measures an idle service."""
    deadline = time.time() + deadline_seconds
    finished: dict[str, dict[str, Any]] = {}
    while len(finished) < len(run_ids) and time.time() < deadline:
        for run_id in run_ids:
            if run_id in finished:
                continue
            run = _get_json(base, f"/api/runs/{run_id}")
            if run and (run.get("state") == "done" or run.get("terminal_status")):
                finished[run_id] = run
        if len(finished) < len(run_ids):
            time.sleep(poll_seconds)
    return [finished.get(r, {"id": r, "state": "never finished"}) for r in run_ids]


def _burst(base: str, size: int) -> list[dict[str, Any]]:
    """`size` submissions in flight at once. Sequential submission would let the first run
    finish before the last one arrives and would measure nothing."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=size) as pool:
        futures = [pool.submit(_submit, base, LOAD_TASKS[i % len(LOAD_TASKS)])
                   for i in range(size)]
        return [f.result() for f in futures]


def qualified(value: Any, measured_under: str) -> dict[str, Any]:
    """A number and the conditions it was measured under, in one object (A17.13).

    Not a stylistic choice. "430 runs/min" measured on fixture pages with no model call in
    the loop is not this system's throughput, and a qualifier that lives in a footnote is a
    qualifier that gets dropped the first time the number is quoted.
    """
    return {"value": value, "measured_under": measured_under}


# ---- the three measurements ------------------------------------------------------

def measure_saturation(base: str, sizes: list[int],
                       deadline_seconds: float) -> dict[str, Any]:
    """The burst size at which the deployment starts refusing, and what it refuses with."""
    steps = []
    saturated_at = None
    for size in sizes:
        results = _burst(base, size)
        # A refusal carries a `run_id` too — the run exists, it is just already over. Only
        # the status code says whether it was admitted, and reading the body instead
        # counted every refusal as an acceptance.
        admitted = [r for r in results if r.get("http") == 202]
        refused = [r for r in results if r.get("http") != 202]
        classes = sorted({r.get("failure_class") or f"http_{r.get('http')}"
                          for r in refused})
        steps.append({"burst": size, "admitted": len(admitted),
                      "refused": len(refused), "refused_as": classes})
        if refused and saturated_at is None:
            saturated_at = size
        _drain(base, [r["run_id"] for r in admitted if r.get("run_id")], deadline_seconds)
    return {
        "sweep": steps,
        "saturation_point": qualified(
            saturated_at,
            f"fixture tasks on the deterministic path, submitted as simultaneous bursts of "
            f"{sizes}; no model call in the loop"),
        "reading": ("no burst in this sweep was refused; the saturation point is above "
                    f"{max(sizes)} concurrent submissions"
                    if saturated_at is None else
                    f"a burst of {saturated_at} is the first to be refused"),
        "depends_on_run_duration": (
            "The onset is a property of the workload as well as the queue. These runs take "
            "well under a second, so some finish while the burst is still arriving and the "
            "queue drains underneath it. A model-driven run takes tens of seconds and "
            "nothing drains during a burst, so refusal begins at the first submission past "
            "the configured capacity (concurrency + depth)."),
    }


def measure_throughput(base: str, clients: int, duration_seconds: float) -> dict[str, Any]:
    """Sustained throughput: keep the queue busy for a fixed window and count completions.

    Closed-loop on purpose. Firing one large burst and timing it measures how fast the
    system empties a queue it was allowed to fill once — everything past the capacity limit
    is refused and never counted, so the figure describes a burst, not a rate. Here each
    client submits again as soon as its previous run finishes, which is what a queue under
    continuous demand actually looks like.
    """
    started = time.time()
    deadline = started + duration_seconds
    completed: list[dict[str, Any]] = []
    refusals = 0
    lock = threading.Lock()

    def client(index: int) -> None:
        nonlocal refusals
        i = index
        while time.time() < deadline:
            result = _submit(base, LOAD_TASKS[i % len(LOAD_TASKS)])
            i += len(LOAD_TASKS)
            if result.get("http") != 202:
                with lock:
                    refusals += 1
                time.sleep(0.2)
                continue
            run_id = result.get("run_id")
            if not run_id:
                continue
            # Polled tightly: a one-second poll would add a second of measured latency to
            # a run that takes a fifth of one, and the throughput figure would be the
            # poller's.
            finished = _drain(base, [run_id], max(5.0, deadline - time.time() + 60),
                              poll_seconds=0.1)
            with lock:
                completed.extend(r for r in finished if r.get("terminal_status"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
        list(pool.map(client, range(clients)))
    elapsed = time.time() - started

    def latency_field(name: str) -> list[float]:
        return [r["latency"][name] for r in completed
                if isinstance(r.get("latency"), dict)
                and r["latency"].get(name) is not None]

    return {
        "clients": clients,
        "window_seconds": round(elapsed, 2),
        "completed": len(completed),
        "refused_at_admission": refusals,
        "runs_per_minute": qualified(
            round(len(completed) / elapsed * 60, 2) if elapsed else None,
            f"{clients} closed-loop clients over {round(elapsed)}s on fixture tasks, "
            f"deterministic path, no model call in the loop — not system throughput for "
            f"model-driven work"),
        "queue_wait_seconds": _spread(latency_field("queue_wait_seconds")),
        "run_seconds": _spread(latency_field("run_seconds")),
        "load_profile": "fixture tasks on the deterministic path — no model call",
    }


def measure_cold_start(port: int, deadline_seconds: float = 120.0) -> dict[str, Any]:
    """Process start to first healthy response (A8.5), measured on a throwaway data
    directory so a cold start is genuinely cold: an empty store, a browser to launch and
    the startup demonstrations to execute."""
    data_dir = tempfile.mkdtemp(prefix="loadtest-cold-")
    # A throwaway directory is not a mounted volume, and the store is right to refuse one
    # in production. This is a measurement of boot time, not a deployment.
    env = {**os.environ, "DATA_DIR": data_dir, "PORT": str(port),
           "APP_ENV": "dev", "REQUIRE_PERSISTENT_STORE": "false"}
    base = f"http://127.0.0.1:{port}"
    started = time.time()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    first_response = None
    first_healthy = None
    try:
        while time.time() - started < deadline_seconds:
            if process.poll() is not None:
                stderr = (process.stderr.read() or b"").decode("utf-8", "replace")
                return {"error": "the server exited during startup",
                        "stderr_tail": stderr[-800:]}
            health = _get_json(base, "/healthz", timeout=5.0)
            if health is not None:
                first_response = first_response or round(time.time() - started, 2)
                if health.get("ok"):
                    first_healthy = round(time.time() - started, 2)
                    break
            time.sleep(0.25)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(data_dir, ignore_errors=True)

    local = ("a local process with an empty data directory: no image pull, no container "
             "scheduling, no platform routing")
    return {
        "seconds_to_first_response": qualified(first_response, local),
        "seconds_to_healthy": qualified(first_healthy, local),
        "note": ("This is process start, not deployment. The number a grader experiences "
                 "includes image pull and container scheduling and is measured end to end "
                 "from outside by `eval.coldstart` at a real redeploy (A17.14)."),
    }


def project_model_driven(concurrency: int, median_run_seconds: float) -> dict[str, Any]:
    """What the measured capacity means for the workload a grader actually submits.

    The load above runs on the fixture with no model call, so its throughput is a property
    of the queue and the browser pool. A model-driven run is dominated by provider latency,
    and its ceiling is arithmetic once the per-run duration is known: `concurrency` runs
    proceed at once, each taking about as long as the eval split measured. Stated as a
    projection, from a measured input, rather than presented as something that was observed.
    """
    return {
        "concurrency": concurrency,
        "median_model_driven_run_seconds": median_run_seconds,
        "projected_runs_per_minute": qualified(
            round(concurrency / median_run_seconds * 60, 2),
            "a projection, not an observation: arithmetic from the concurrency limit and "
            "the median model-driven run duration measured by the eval harness"),
        "basis": ("arithmetic from the concurrency limit and the median model-driven run "
                  "duration measured by the eval harness; not observed under load"),
    }


def _spread(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(float(v) for v in values)
    return {"n": len(ordered), "median": round(statistics.median(ordered), 2),
            "min": round(ordered[0], 2), "max": round(ordered[-1], 2)}


# ---- entry point -----------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--sweep", default="1,2,3,4,6",
                        help="burst sizes to submit simultaneously")
    parser.add_argument("--clients", type=int, default=4,
                        help="concurrent clients kept submitting during the window")
    parser.add_argument("--duration", type=float, default=30.0,
                        help="seconds to sustain the throughput measurement")
    parser.add_argument("--deadline", type=float, default=240.0)
    parser.add_argument("--cold-start", action="store_true",
                        help="also start a local server on a throwaway store and time it")
    parser.add_argument("--cold-start-port", type=int, default=8123)
    parser.add_argument("--model-run-seconds", type=float,
                        help="median model-driven run duration from the eval harness; turns "
                             "the measured capacity into a projection for real traffic")
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    health = _get_json(base, "/healthz")
    if health is None:
        raise SystemExit(f"{base}/healthz did not answer; nothing to measure")

    sizes = [int(s) for s in args.sweep.split(",") if s.strip()]
    report: dict[str, Any] = {
        "provenance": {
            "tool": LOADTEST_VERSION,
            "base_url": base,
            "git_sha": health.get("git_sha"),
            "configured_queue": health.get("queue"),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "saturation": measure_saturation(base, sizes, args.deadline),
        "throughput": measure_throughput(base, args.clients, args.duration),
    }
    if args.model_run_seconds:
        report["model_driven_projection"] = project_model_driven(
            int((health.get("queue") or {}).get("concurrency") or 2),
            args.model_run_seconds)
    if args.cold_start:
        report["cold_start"] = measure_cold_start(args.cold_start_port)
    report["provenance"]["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out = args.out or (REPO / "eval" / "results" /
                       f"load-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    print(f"\nwritten {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

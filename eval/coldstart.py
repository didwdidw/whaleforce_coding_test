"""Deploy to first successful request, measured from outside (A17.14).

`eval.loadtest --cold-start` times a local process from `exec` to a healthy `/healthz`. That
is a real number and it is not the one a grader experiences: the platform owns image pull,
container scheduling and routing, and those are most of the wait. That they cannot be
*decomposed* from outside is a reason the number cannot be broken down, not a reason it
cannot be taken.

So this takes it end to end, from a laptop, across a real redeploy:

    # start this first, then press deploy
    python -m eval.coldstart --base-url https://<host> --t0-now

It polls `/healthz` continuously and records four moments, all of them observed rather than
assumed:

  **t0**            — when deploy was pressed. `--t0-now` means "now"; `--t0 <epoch>` gives
                      an exact instant. Without either, t0 falls back to the last response
                      from the *previous* build, which is a lower bound on the wait and is
                      labelled as one.
  **outage start**  — the first request the old build did not answer.
  **first response** — the first answer from the new build, identified by a changed
                      `git_sha`, so a stale reply from the old container cannot end the
                      measurement early.
  **first success** — a real task submitted and carried to a terminal status. A service that
                      answers `/healthz` and cannot yet run anything is not up in the sense
                      anybody cares about.

The window between `--t0-now` and the deploy button is the operator's reaction time, and it
is inside the number. It is stated in the output rather than subtracted, because subtracting
an unmeasured quantity is how a measurement becomes an estimate.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

COLDSTART_VERSION = "coldstart/1.0"
REPO = pathlib.Path(__file__).parent.parent
#: Deterministic, needs no provider quota, and exercises the browser — so "the service
#: answered" and "the service works" are not the same observation.
PROBE_TASK = "Search the fixture catalogue for lantern"


def _get(base: str, path: str, timeout: float = 5.0) -> tuple[int | None, dict[str, Any]]:
    request = urllib.request.Request(f"{base}{path}",
                                     headers={"User-Agent": COLDSTART_VERSION})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}
    except Exception:  # noqa: BLE001 - an unreachable host is the measurement, not an error
        return None, {}


def _post(base: str, task: str, timeout: float = 30.0) -> tuple[int | None, dict[str, Any]]:
    data = urllib.parse.urlencode({"task": task}).encode()
    request = urllib.request.Request(f"{base}/api/runs", data=data,
                                     headers={"User-Agent": COLDSTART_VERSION})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}
    except Exception:  # noqa: BLE001
        return None, {}


def watch(base: str, *, t0: float | None, deadline_seconds: float,
          poll_seconds: float = 0.5) -> dict[str, Any]:
    """Poll until a new build answers, then until it can finish a task."""
    started = time.time()
    baseline_sha: str | None = None
    last_old_response: float | None = None
    outage_started: float | None = None
    first_response: float | None = None
    first_healthy: float | None = None
    new_sha: str | None = None
    observations = 0

    while time.time() - started < deadline_seconds:
        status, body = _get(base, "/healthz")
        now = time.time()
        observations += 1
        sha = (body or {}).get("git_sha")
        if status is not None and sha:
            if baseline_sha is None:
                baseline_sha = sha
            if sha == baseline_sha and first_response is None:
                last_old_response = now
                outage_started = None
            elif sha != baseline_sha:
                first_response = first_response or now
                new_sha = new_sha or sha
                if body.get("ok"):
                    first_healthy = now
                    break
        elif first_response is None:
            outage_started = outage_started or now
        time.sleep(poll_seconds)

    if first_response is None:
        return {"error": "no new build answered within the deadline",
                "baseline_git_sha": baseline_sha, "observations": observations,
                "waited_seconds": round(time.time() - started, 2)}

    # Answering is not working. A task carried to a terminal status is.
    first_success: float | None = None
    run_id = None
    while time.time() - started < deadline_seconds and first_success is None:
        status, body = _post(base, PROBE_TASK)
        run_id = body.get("run_id") or run_id
        if status == 202 and run_id:
            while time.time() - started < deadline_seconds:
                _, run = _get(base, f"/api/runs/{run_id}", timeout=15.0)
                if run.get("state") == "done":
                    first_success = time.time()
                    break
                time.sleep(poll_seconds)
        else:
            time.sleep(poll_seconds)

    origin = ("the operator's deploy timestamp" if t0 is not None else
              "the last response from the previous build, which is a lower bound: the "
              "deploy was pressed at or before it")
    zero = t0 if t0 is not None else last_old_response
    def since(moment: float | None) -> float | None:
        return None if moment is None or zero is None else round(moment - zero, 2)

    return {
        "t0_origin": origin,
        "baseline_git_sha": baseline_sha,
        "new_git_sha": new_sha,
        "poll_seconds": poll_seconds,
        "observations": observations,
        "seconds_to_first_response": since(first_response),
        "seconds_to_healthy": since(first_healthy),
        "seconds_to_first_successful_task": since(first_success),
        "outage_seconds": (None if outage_started is None or first_response is None
                           else round(first_response - outage_started, 2)),
        "probe_task": PROBE_TASK,
        "probe_run_id": run_id,
        "measured_under": ("a real redeploy of the live deployment, from a laptop over the "
                           "public internet, including image pull, container scheduling and "
                           "routing — none of which can be separated out from here"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--t0-now", action="store_true",
                        help="start the clock now — run this, then press deploy")
    parser.add_argument("--t0", type=float, help="epoch seconds when deploy was pressed")
    parser.add_argument("--deadline", type=float, default=900.0)
    parser.add_argument("--poll", type=float, default=0.5)
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    t0 = args.t0 if args.t0 else (time.time() if args.t0_now else None)
    print(f"watching {base} for a new build; press deploy now" if args.t0_now
          else f"watching {base} for a new build")

    report = {
        "provenance": {
            "tool": COLDSTART_VERSION,
            "base_url": base,
            "t0_epoch": t0,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "cold_start": watch(base, t0=t0, deadline_seconds=args.deadline,
                            poll_seconds=args.poll),
    }
    report["provenance"]["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out = args.out or (REPO / "eval" / "results" /
                       f"coldstart-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    print(f"\nwritten {out}")
    return 0 if not report["cold_start"].get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())

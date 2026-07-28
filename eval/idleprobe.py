"""Cold arrival: what a grader gets opening a URL nobody has touched for hours (A18.8).

This is not the deploy-to-usable number. It is the other one — and it is only non-zero if
the deployment can actually go cold. Whether it can has to be established rather than
assumed, and the way to establish it is to leave it alone and then look at its own clock:

    python -m eval.idleprobe mark  --base-url https://<host>     # then send it no traffic
    python -m eval.idleprobe probe --base-url https://<host>     # hours later

`uptime_seconds` at the end of the window against the length of the window answers the
question directly. If the process ran continuously across an idle window of hours, nothing
evicted it and nothing scaled it to zero, so there is no cold arrival to measure on this
deployment and the report says that, with the window it was established over. If uptime is
*shorter* than the window, the container did restart — and then the first request after
idle is a real cold start and its number is the one that matters.

Either way the probe submits one task and reports its latency **separately** from the
steady-state median (A18.9): that first request is the one a grader forms an impression on,
and burying it in a median describes nobody's experience.

The window must be genuinely idle. Polling it to see whether it went cold is what keeps it
warm, so this takes exactly two readings: one at each end.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from typing import Any

from eval.http_client import get_json, post_form

IDLEPROBE_VERSION = "idleprobe/1.0"
REPO = pathlib.Path(__file__).parent.parent
DEFAULT_STATE = REPO / "eval" / "results" / "idle-mark.json"
#: Scripted and deterministic: a first-request latency that includes a model call measures
#: the provider's queue as much as ours. Cold arrival is about the container waking up.
PROBE_TASK = "Search the fixture catalogue for lantern"


def _health(base: str) -> dict[str, Any]:
    status, body = get_json(base, "/healthz", timeout=30.0, user_agent=IDLEPROBE_VERSION)
    if status is None:
        raise SystemExit(f"{base}/healthz did not answer")
    return body


def mark(base: str, state_path: pathlib.Path) -> dict[str, Any]:
    health = _health(base)
    record = {"tool": IDLEPROBE_VERSION, "base_url": base, "at_epoch": time.time(),
              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "git_sha": health.get("git_sha"), "uptime_seconds": health.get("uptime_seconds")}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


def probe(base: str, state_path: pathlib.Path, *, deadline: float = 120.0) -> dict[str, Any]:
    if not state_path.is_file():
        raise SystemExit(f"no idle mark at {state_path}: run `mark` first, then leave the "
                         f"deployment alone. Without a marked start there is no window.")
    marked = json.loads(state_path.read_text(encoding="utf-8"))
    idle_seconds = time.time() - marked["at_epoch"]

    health = _health(base)
    uptime = float(health.get("uptime_seconds") or 0.0)
    same_build = health.get("git_sha") == marked.get("git_sha")
    # Ran right through the window: nothing evicted it, nothing scaled it to zero.
    continuous = same_build and uptime >= idle_seconds

    submitted_at = time.time()
    status, body = post_form(base, "/api/runs", {"task": PROBE_TASK}, timeout=60.0,
                             user_agent=IDLEPROBE_VERSION)
    run_id = (body or {}).get("run_id")
    run: dict[str, Any] = {}
    if status == 202 and run_id:
        while time.time() - submitted_at < deadline:
            _, run = get_json(base, f"/api/runs/{run_id}", timeout=30.0,
                              user_agent=IDLEPROBE_VERSION)
            if (run or {}).get("state") == "done":
                break
            time.sleep(0.5)
    finished_at = time.time()

    return {
        "tool": IDLEPROBE_VERSION,
        "base_url": base,
        "idle_window_seconds": round(idle_seconds, 1),
        "idle_window_hours": round(idle_seconds / 3600.0, 2),
        "marked_at": marked.get("at"),
        "git_sha": health.get("git_sha"),
        "same_build_as_marked": same_build,
        "uptime_seconds_at_end": uptime,
        "process_ran_through_the_window": continuous,
        "cold_arrival": {
            "value": 0.0 if continuous else round(finished_at - submitted_at, 2),
            "measured_under": (
                f"structurally zero on this deployment: the application process ran "
                f"continuously across an idle window of {idle_seconds / 3600.0:.2f} h with "
                f"no traffic from us, so nothing evicted it and nothing scaled it to zero. "
                f"Established over that window, not assumed."
                if continuous else
                f"the container did not run through the idle window "
                f"({uptime:.0f}s uptime against a {idle_seconds:.0f}s window"
                + ("" if same_build else ", and the build changed — a deploy happened, so "
                                         "this is not an eviction measurement")
                + "), so this is a real cold arrival: submit to terminal status, client "
                  "side, over the public internet"),
        },
        # A18.9: reported outside the steady-state median, whatever it turns out to be.
        "first_task_after_idle": {
            "task": PROBE_TASK,
            "run_id": run_id,
            "terminal_status": (run or {}).get("terminal_status"),
            "client_observed_seconds": round(finished_at - submitted_at, 2),
            "server_side_latency": (run or {}).get("latency"),
            "measured_under": ("one request, the first after the idle window above. It is "
                               "not part of any median: it is the request a grader's first "
                               "impression is formed on."),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("mark", "probe"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--state", type=pathlib.Path, default=DEFAULT_STATE)
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    if args.action == "mark":
        record = mark(base, args.state)
        print(json.dumps(record, indent=1))
        print(f"\nmarked. Send this deployment no traffic until the probe.")
        return 0

    report = probe(base, args.state)
    out = args.out or (REPO / "eval" / "results" /
                       f"coldarrival-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    print(f"\nwritten {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The workload that runs scored splits (A12.3, A18.10).

Scored runs must use the billing credential, and the billing credential must never sit on
the filesystem of the container serving anonymous traffic. Those two rules together mean an
eval split cannot be driven at the public URL — pointing the harness there does not just
spend the wrong quota, it measures a process that is forbidden from holding the key the
split is supposed to run on.

So the harness comes to the workload instead of the workload being exposed to the harness.
This module runs inside a second container built from the same image:

  1. it refuses to start unless it is configured to be that workload,
  2. it starts the application server on **loopback only** — not merely unpublished, but
     unreachable even from the platform's private network,
  3. it drives the splits over HTTP against that loopback server, which is why the harness
     is still measuring a deployed system rather than an import,
  4. it writes each result onto the shared volume, where the public service can serve it
     read-only, and where the artifacts those runs produced already live,
  5. it releases the browser and idles.

It does not re-run a split whose result file already exists. A container restart is free
for the platform to do and is not free for us: an automatic restart loop that re-ran a paid
split would spend real money on a schedule and overwrite the result it spent it on.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

from app.config import settings
from eval.harness import BROWSER_TASK, DEFAULT_CASES, run_split

WORKLOAD_VERSION = "scored-workload/1.0"
LOOPBACK = "127.0.0.1"


def _refuse(reason: str) -> None:
    raise SystemExit(f"REFUSING TO RUN THE SCORED WORKLOAD: {reason}")


def preflight() -> None:
    """Every condition that makes this workload the right place to score, checked loudly.

    A split that runs anyway under the wrong credential produces a number that looks like
    every other number in the results directory.
    """
    policy = settings.provider.credential_policy
    if policy != "scored":
        _refuse(f"CREDENTIAL_POLICY is {policy!r}, not 'scored'. A9.6 requires the billing "
                f"credential for validation and test splits, and running them on the free "
                f"tier risks losing a split that cannot be re-run to quota exhaustion.")
    key_path = settings.provider.key_dir / settings.provider.paid_key_name
    if not key_path.is_file():
        _refuse(f"no billing credential at {key_path}. It is placed by the operator in the "
                f"platform's config editor, outside the artifact store's tree.")
    if settings.data_dir == pathlib.Path("/data/task1") and not settings.data_dir.is_dir():
        _refuse(f"{settings.data_dir} does not exist: the shared volume is not mounted, so "
                f"the evidence from scored runs would not reach the public run views.")


def start_server(port: int, log_path: pathlib.Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", LOOPBACK, "--port", str(port), "--log-level", "info",
         "--timeout-keep-alive", "65"],
        stdout=handle, stderr=subprocess.STDOUT,
        env={**os.environ, "APP_ROLE": "scored"})


def wait_until_healthy(base: str, deadline_seconds: float) -> dict:
    """Healthy means the store is writable and the browser is connected, not that a port
    is open: a split started against a half-open server scores its own startup."""
    started = time.time()
    last = {}
    while time.time() - started < deadline_seconds:
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=10) as response:
                last = json.loads(response.read())
                if last.get("ok"):
                    return last
        except urllib.error.HTTPError as exc:
            try:
                last = json.loads(exc.read())
            except ValueError:
                last = {}
        except Exception:  # noqa: BLE001 - not up yet is the expected case here
            pass
        time.sleep(1.0)
    _refuse(f"the loopback server was not healthy within {deadline_seconds:.0f}s: "
            f"{last.get('unhealthy_because') or 'no response'}")


def result_path(split: str, git_sha: str, round_id: str) -> pathlib.Path:
    return settings.eval_results_dir / f"{split}-deploy-{git_sha}-r{round_id}.json"


def run(splits: list[str], *, port: int, round_id: str, force: bool,
        deadline: float, startup_deadline: float, idle: bool) -> int:
    preflight()
    base = f"http://{LOOPBACK}:{port}"
    log_path = settings.data_dir / "logs" / "scored-workload.log"
    server = start_server(port, log_path)
    written: list[str] = []
    try:
        health = wait_until_healthy(base, startup_deadline)
        git_sha = (health.get("git_sha") or "unknown")[:12]
        settings.eval_results_dir.mkdir(parents=True, exist_ok=True)
        for split in splits:
            out = result_path(split, git_sha, round_id)
            if out.exists() and not force:
                print(f"[{WORKLOAD_VERSION}] {split}: {out.name} already exists; not "
                      f"re-running. A restart must not re-spend a scored split.")
                continue
            cases = DEFAULT_CASES.get(split)
            if cases is None or not cases.exists():
                print(f"[{WORKLOAD_VERSION}] {split}: no case file in this image "
                      f"({cases}); skipped. Held-out splits are mounted, not built in.")
                continue
            print(f"[{WORKLOAD_VERSION}] {split}: starting against {base}")
            report = run_split(base, split, cases, deadline,
                               verbose=split in ("dev", "experimental"),
                               schema=BROWSER_TASK)
            out.write_text(json.dumps(report, indent=1), encoding="utf-8")
            written.append(out.name)
            print(f"[{WORKLOAD_VERSION}] {split}: written {out}")
            print(json.dumps(report["aggregate"], indent=1))
    finally:
        # Give the RAM back. A container idling with a live Chrome costs the host the same
        # as one doing work, and the app service needs that headroom.
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()

    print(f"[{WORKLOAD_VERSION}] done. Wrote: {', '.join(written) or 'nothing'}")
    if idle:
        # Exiting would have the platform restart us, and a restart is another split round.
        print(f"[{WORKLOAD_VERSION}] idling. Change EVAL_ROUND and restart to score again.")
        while True:
            time.sleep(3600)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits", default=os.environ.get("EVAL_SPLITS", "dev,experimental"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("EVAL_PORT", "8080")))
    parser.add_argument("--round", default=os.environ.get("EVAL_ROUND", "1"))
    parser.add_argument("--force", action="store_true",
                        default=os.environ.get("EVAL_FORCE", "") == "1")
    parser.add_argument("--deadline", type=float, default=300.0)
    parser.add_argument("--startup-deadline", type=float, default=180.0)
    parser.add_argument("--no-idle", action="store_true")
    args = parser.parse_args(argv)
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    if not splits:
        _refuse("no splits requested")
    return run(splits, port=args.port, round_id=args.round, force=args.force,
               deadline=args.deadline, startup_deadline=args.startup_deadline,
               idle=not args.no_idle)


if __name__ == "__main__":
    raise SystemExit(main())

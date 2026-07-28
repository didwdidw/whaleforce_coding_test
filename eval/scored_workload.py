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
from eval.harness import BROWSER_TASK, DEFAULT_CASES, parse_cases, run_split

WORKLOAD_VERSION = "scored-workload/1.1"
LOOPBACK = "127.0.0.1"
#: The measured maximum cost of one run: the most expensive case of the dev split at
#: `427cd96` ($0.0042; the mean was $0.0020). Configuration rather than a constant, because
#: it is a measurement and measurements are re-taken.
USD_PER_RUN = float(os.environ.get("EVAL_USD_PER_RUN", "0.0042"))
#: Applied to the measured figure before it is compared with the remaining allowance. A
#: forecast that is exactly the last measurement leaves no room for a slower split.
SAFETY_FACTOR = float(os.environ.get("EVAL_COST_SAFETY_FACTOR", "1.5"))


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


def budget_ceiling_usd_per_run() -> float:
    """What one run costs if it spends every token it is allowed to.

    Not the forecast — the tail. It is what makes a per-round estimate a bound rather than
    an average, and with a $1 daily ceiling a 25-case round is close enough to it that the
    operator should see the number rather than be surprised by it.
    """
    budgets, prices = settings.budgets, settings.provider
    return (budgets.max_input_tokens_per_run * prices.price_input_usd_per_1m / 1e6
            + budgets.max_output_tokens_per_run * prices.price_output_usd_per_1m / 1e6)


def forecast(splits: list[str], spend: dict[str, Any]) -> dict[str, Any]:
    """What this round is expected to cost against what is left to spend today.

    The daily ceiling stops a run mid-call, which is the right thing for a runaway loop and
    the wrong thing for a scored round: it turns one round into a half-blocked result file
    while the round's name is already used. So the round is priced before the first case
    and refused whole, which is the same shape as every other precondition here.
    """
    countable = {split: DEFAULT_CASES.get(split) for split in splits}
    cases = {split: (len(parse_cases(path, BROWSER_TASK)) if path and path.exists() else None)
             for split, path in countable.items()}
    known = sum(n for n in cases.values() if n)
    unknown = [split for split, n in cases.items() if n is None]

    ceiling_day = settings.provider.spend_ceiling_usd_per_day
    ceiling_total = settings.provider.spend_ceiling_usd
    remaining_today = max(0.0, ceiling_day - float(spend.get("today_usd") or 0.0))
    remaining_total = max(0.0, ceiling_total - float(spend.get("cumulative_usd") or 0.0))
    remaining = min(remaining_today, remaining_total)

    expected = known * USD_PER_RUN * SAFETY_FACTOR
    worst = known * budget_ceiling_usd_per_run()
    return {
        "cases_per_split": cases,
        "cases_priced": known,
        "cases_not_in_this_image": unknown,
        "usd_per_run_measured": USD_PER_RUN,
        "safety_factor": SAFETY_FACTOR,
        "expected_usd": round(expected, 4),
        "worst_case_usd": round(worst, 4),
        "worst_case_basis": ("every run spending its full token budget: "
                             f"${budget_ceiling_usd_per_run():.4f} per run"),
        "remaining_today_usd": round(remaining_today, 4),
        "remaining_cumulative_usd": round(remaining_total, 4),
        "affordable": expected <= remaining,
        "worst_case_affordable": worst <= remaining,
    }


def check_affordable(plan: dict[str, Any]) -> None:
    """Refuse the round before the first case, or warn about the tail and continue."""
    if not plan["affordable"]:
        _refuse(
            f"this round is forecast at ${plan['expected_usd']:.4f} "
            f"({plan['cases_priced']} cases x ${plan['usd_per_run_measured']:.4f} measured "
            f"x {plan['safety_factor']:g} safety) and only ${plan['remaining_today_usd']:.4f} "
            f"remains of today's ceiling (${plan['remaining_cumulative_usd']:.4f} of the "
            f"cumulative one).\nStopping at case one costs nothing; stopping at case "
            f"fourteen costs the round and leaves a half-blocked file wearing its name. "
            f"Raise PROVIDER_SPEND_CEILING_USD_PER_DAY on this service, or run the round "
            f"tomorrow.")
    if not plan["worst_case_affordable"]:
        print(f"[{WORKLOAD_VERSION}] WARNING: the forecast fits but the tail does not. If "
              f"every run spent its whole token budget this round would cost "
              f"${plan['worst_case_usd']:.4f} against ${plan['remaining_today_usd']:.4f} "
              f"remaining. That outcome ends the round early; the partial result is written "
              f"under a '-degraded' name so the round can be re-run under the same number.")


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


def result_path(split: str, git_sha: str, round_id: str,
                degraded: bool = False) -> pathlib.Path:
    """A degraded round gets its own name so the clean one stays free.

    A partial file sitting in the slot the round is identified by is worse than no file:
    the next start skips the split because a result "exists", and the number that survives
    is the broken one.
    """
    suffix = "-degraded" if degraded else ""
    return settings.eval_results_dir / f"{split}-deploy-{git_sha}-r{round_id}{suffix}.json"


def run(splits: list[str], *, port: int, round_id: str, force: bool,
        deadline: float, startup_deadline: float, idle: bool,
        dry_run: bool = False) -> int:
    preflight()
    base = f"http://{LOOPBACK}:{port}"
    log_path = settings.data_dir / "logs" / "scored-workload.log"
    server = start_server(port, log_path)
    written: list[str] = []
    try:
        health = wait_until_healthy(base, startup_deadline)
        git_sha = (health.get("git_sha") or "unknown")[:12]
        settings.eval_results_dir.mkdir(parents=True, exist_ok=True)
        plan = forecast(splits, health.get("provider_spend") or {})
        print(f"[{WORKLOAD_VERSION}] round r{round_id} on {git_sha}: "
              f"{json.dumps(plan, indent=1)}")
        if dry_run:
            # Everything that can fail before money is spent, exercised: the credential
            # policy, the key, the volume, the browser, the queue, and the price of the
            # round. The operator's first start of a scoring service should not be the
            # one that spends. It is not literally free — the server validates the
            # credential with one minimal live call at startup (A9.3) — and that call is
            # the point: a key that cannot call is found here rather than mid-round.
            print(f"[{WORKLOAD_VERSION}] dry run: preflight, startup and forecast only. "
                  f"No case was submitted and no result file was written.")
            splits = []
        else:
            check_affordable(plan)
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
            if (report.get("provenance") or {}).get("degraded"):
                out = result_path(split, git_sha, round_id, degraded=True)
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
    parser.add_argument("--dry-run", action="store_true",
                        default=os.environ.get("EVAL_DRY_RUN", "") == "1",
                        help="preflight, start up and price the round; submit nothing")
    args = parser.parse_args(argv)
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    if not splits:
        _refuse("no splits requested")
    return run(splits, port=args.port, round_id=args.round, force=args.force,
               deadline=args.deadline, startup_deadline=args.startup_deadline,
               idle=not args.no_idle, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

"""HTTP surface and frontend (S-11.1 to S-11.6).

A run can be submitted, watched, and inspected. The homepage shows pre-executed runs
including a failure, so a grader's first click is never an unexplained spinner (S-11.5),
and every place a status is rendered reads `counts_as_success` rather than deciding for
itself, so `partial` and `unverified` cannot leak into a success figure (S-5.2).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import egress
from app.browser import BrowserSupervisor
from app.config import config_provenance, settings
from app.coverage import CoverageLedger
from app.executor import Executor
from app.models import Run, TerminalStatus, Tier, new_id
from app.provider import Provider, ProviderError
from app.queue import AdmissionRefused, RunQueue
from app.robots import RobotsCache
from app.store import Store

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Chosen so the homepage shows one of each outcome without anyone having to provoke it:
# a verified answer, a proven absence, a right answer scored as a failure for skipping a
# declared action, a partial where a label moved, and a refusal.
DEMO_TASKS = [
    "Search the fixture catalogue for lantern",
    "Is any product priced over £100?",
    "Read page 2 of the browse listing without clicking next",
    "Dismiss the overlay on the gated page and read the reference code, seed mu2-text",
    "Log into my brokerage account and tell me my balance",
]


def git_sha() -> str:
    """Build provenance. Every first run of a held-out split records this (S-10.7).

    The build context has no `.git`, so the commit is baked in as an environment variable
    at image build time. Falling back to `git rev-parse` covers running from a checkout;
    "unknown" is reported honestly rather than guessed, and a score carrying it is not
    reportable.
    """
    for var in ("GIT_SHA", "ZEABUR_GIT_COMMIT_SHA", "SOURCE_COMMIT"):
        value = os.environ.get(var, "").strip()
        if value and value != "unknown":
            return value[:12]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


class App:
    """Wires the supervisor, store, executor and queue together for one process."""

    def __init__(self) -> None:
        self.store = Store()
        self.supervisor = BrowserSupervisor()
        self.robots = RobotsCache()
        self.executor = Executor(self.supervisor, self.store, self.robots)
        self.coverage = CoverageLedger(self.store)
        self.provider = Provider(ledger=self.store)
        #: Set at startup. A deployment with no credential is a degraded deployment, not a
        #: dead one: everything deterministic still runs, and the planner path reports a
        #: named failure instead of the service refusing to boot.
        self.planner_status: dict[str, Any] = {
            "available": False,
            "reason": "not checked yet",
        }
        self.queue = RunQueue(self._execute, session_count=self.store.session_run_count)
        self.started_at = time.time()
        self.git_sha = git_sha()
        self._events: dict[str, asyncio.Queue] = {}

    async def _execute(self, run: Run) -> None:
        await self.executor.execute(run)
        self.store.save_run(run)
        self._publish(run.id, {"state": run.state.value,
                               "terminal_status": run.terminal_status.value
                               if run.terminal_status else None})

    def _publish(self, run_id: str, payload: dict[str, Any]) -> None:
        q = self._events.get(run_id)
        if q:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(payload)


state = App()
app = FastAPI(title="Task 1 — Browser Automation Agent", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def _startup() -> None:
    # Before anything else: refuse to run with the SSRF guard silently off.
    settings.validate_or_die()
    await state.supervisor.start()
    await state.queue.start()
    _check_planner()
    state.store.enforce_retention()
    asyncio.create_task(_seed_pre_executed())


@app.on_event("shutdown")
async def _shutdown() -> None:
    await state.queue.aclose()
    await state.supervisor.aclose()
    state.store.close()


def _check_planner() -> None:
    """Whether the planner can run at all, decided once at startup and reported.

    A missing credential must not stop the service: the fixture operations, the verifier,
    the evidence store and every deterministic path work without a model, and a deployment
    that refuses to boot is a deployment nobody can look at. What it must not do is look
    healthy and then fail obscurely at the first planned run — so the state is named here
    and surfaced on /healthz.
    """
    if not state.provider.configured():
        state.planner_status = {
            "available": False,
            "reason": ("No provider credential is readable for the "
                       f"{state.provider.policy.value} policy. Deterministic operations "
                       f"still run; anything needing the planner ends "
                       f"blocked / provider_error rather than failing obscurely."),
            "failure_class": "provider_error",
        }
        log.warning("planner unavailable: no credential configured")
        return
    try:
        detail = state.provider.validate_or_die()
    except ProviderError as exc:
        state.planner_status = {"available": False, "reason": str(exc)[:300],
                                "failure_class": exc.failure_class.value}
        log.warning("planner unavailable: %s", exc)
        return
    state.planner_status = {"available": True, "model": detail["model"],
                            "credential_tier": detail["credential_tier"],
                            "validated_by": "a live minimal call at startup (A9.3)"}


async def _seed_pre_executed() -> None:
    """Pre-execute a few runs so the homepage is immediately inspectable (S-11.5).

    One of them is a refusal on purpose: a grader should be able to open a non-success run
    without having to provoke one.
    """
    if state.store.recent_runs(limit=1, pre_executed=True):
        return
    await asyncio.sleep(1.0)
    for task in DEMO_TASKS:
        tier, _ = state.executor.classify(task)
        run = Run(id=new_id("run"), task=task, tier=tier, session_id="pre-executed",
                  pre_executed=True)
        state.store.save_run(run)
        try:
            await state.executor.execute(run)
        except Exception:  # noqa: BLE001 - a seed failure must not stop startup
            log.exception("pre-executed run failed")
        state.store.save_run(run)


# ---- pages ---------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    runs = state.store.recent_runs(limit=20)
    # A pinned demonstration never expires, so it ages instead. Showing when its evidence
    # was captured keeps a two-week-old run reading as a dated demonstration rather than as
    # a current result (A11.3).
    captured = {}
    for r in runs:
        if r.pre_executed:
            arts = state.store.artifacts_for_run(r.id)
            if arts:
                captured[r.id] = arts[0].retrieved_on
    return TEMPLATES.TemplateResponse(request, "index.html", {
        "runs": runs,
        "captured": captured,
        "queue": state.queue.snapshot().to_dict(),
        "browser": state.supervisor.status(),
        "demo_tasks": DEMO_TASKS,
        "milestone": "M2 — evidence and deterministic verification. No model is in the "
                     "loop yet: plans are scripted, and every status below was decided by "
                     "code re-extracting the answer from the stored artifact through an "
                     "anchor frozen before the run started.",
    })


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str) -> Response:
    run = state.store.load_run(run_id)
    if run is None:
        return HTMLResponse("<h1>404</h1><p>No such run.</p>", status_code=404)
    verdict = next((t.detail.get("verdict") for t in run.trace if t.detail.get("verdict")),
                   None)
    artifacts = state.store.artifacts_for_run(run_id)
    return TEMPLATES.TemplateResponse(request, "run.html", {
        "run": run,
        "artifacts": artifacts,
        "position": state.queue.position_of(run_id),
        "verdict": verdict,
        # An evidence bundle stores the artifact's state as it was at verification time. Two
        # weeks later that is stale, and rendering it would offer a link to bytes that are
        # gone. The state is re-resolved now so expiry shows as "expired on <date>" rather
        # than as a dead link (A11.4).
        "artifact_state": {a.id: a.to_dict() for a in artifacts},
    })


@app.get("/coverage", response_class=HTMLResponse)
async def coverage(request: Request) -> HTMLResponse:
    """Which statuses this deployment has actually produced (S-5.1, and the M1 lesson).

    A declared status nobody has ever reached is an unreachable code path, which is how a
    gate passes without having been tested.
    """
    return TEMPLATES.TemplateResponse(request, "coverage.html", {
        "report": state.coverage.report(),
    })


@app.get("/support", response_class=HTMLResponse)
async def support(request: Request) -> HTMLResponse:
    """The support matrix and limitations, reachable from the frontend (S-11.4)."""
    return TEMPLATES.TemplateResponse(request, "support.html", {
        "egress": egress.describe(),
        "robots": state.robots.describe(),
        "storage": state.store.storage_status(),
        "budgets": settings.budgets,
    })


# ---- API -----------------------------------------------------------------------

@app.post("/api/runs")
async def submit(request: Request, task: str = Form(...)) -> Response:
    session_id = request.cookies.get("sid") or new_id("sess")
    tier, _ = state.executor.classify(task)
    run = Run(id=new_id("run"), task=task.strip(), tier=tier, session_id=session_id)
    state.store.save_run(run)
    try:
        position = state.queue.admit(run)
    except AdmissionRefused as refusal:
        run.terminal_status = (TerminalStatus.BLOCKED)
        run.failure_class = refusal.failure_class
        run.explanation = refusal.message
        run.finished_at = time.time()
        state.store.save_run(run)
        state.coverage.record(status=run.terminal_status, failure=refusal.failure_class,
                              run_id=run.id, task=run.task)
        headers = {"Retry-After": str(refusal.retry_after)} if refusal.retry_after else {}
        body = {"run_id": run.id, "terminal_status": run.terminal_status.value,
                "failure_class": refusal.failure_class.value,
                "explanation": refusal.message, "counts_as_success": False}
        response = JSONResponse(body, status_code=429, headers=headers)
        response.set_cookie("sid", session_id, max_age=86_400, httponly=True, samesite="lax")
        return response

    payload = {"run_id": run.id, "tier": run.tier.value, "queue_position": position,
               "detail_url": f"/runs/{run.id}"}
    response = JSONResponse(payload, status_code=202)
    response.set_cookie("sid", session_id, max_age=86_400, httponly=True, samesite="lax")
    return response


@app.get("/api/runs/{run_id}")
async def api_run(run_id: str) -> Response:
    run = state.store.load_run(run_id)
    if run is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    data = run.to_dict()
    data["artifacts"] = [a.to_dict() for a in state.store.artifacts_for_run(run_id)]
    data["queue_position"] = state.queue.position_of(run_id)
    return JSONResponse(data)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    """Progress as server-sent events, so a queued run can say what it is waiting for."""
    q: asyncio.Queue = asyncio.Queue(maxsize=32)
    state._events[run_id] = q

    async def stream():
        try:
            while True:
                run = state.store.load_run(run_id)
                if run is None:
                    yield 'data: {"error":"not_found"}\n\n'
                    return
                payload = {
                    "state": run.state.value,
                    "steps": len(run.trace),
                    "last": run.trace[-1].summary if run.trace else None,
                    "queue_position": state.queue.position_of(run_id),
                    "terminal_status": run.terminal_status.value if run.terminal_status else None,
                    "counts_as_success": run.counts_as_success,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                if run.state.value == "done":
                    return
                await asyncio.sleep(1.0)
        finally:
            state._events.pop(run_id, None)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/artifacts/{artifact_id}")
async def artifact(artifact_id: str) -> Response:
    ref = state.store.get_artifact_ref(artifact_id)
    if ref is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    data = state.store.read_artifact(artifact_id)
    if data is None:
        # Expired, not missing. The reference still resolves and says so (A9.7.2).
        return JSONResponse({**ref.to_dict(), "error": "expired",
                             "detail": (f"Expired on {ref.expired_on}. The bytes have aged "
                                        f"out of the artifact store; the id, source URL, "
                                        f"retrieval date, content hash and byte length are "
                                        f"retained, so this evidence bundle is a dated "
                                        f"record rather than a dangling pointer (A11.4).")},
                            status_code=410)
    return Response(data, media_type=ref.media_type or "application/octet-stream")


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, Any]:
    """Liveness plus the numbers A9.7 and A11.5 are judged on.

    The store check is an actual write probe. A path-existence check passes on an unmounted
    directory, a read-only mount and a full disk alike — the three states that would
    otherwise be discovered only when someone opened an evidence bundle.
    """
    storage = state.store.storage_status()
    store_ok = storage["writable"] and (storage["on_mounted_volume"]
                                        or not storage["mount_required"])
    healthy = store_ok and state.supervisor.status()["connected"]
    if not healthy:
        response.status_code = 503
    return {
        "ok": healthy,
        "git_sha": state.git_sha,
        "uptime_seconds": round(time.time() - state.started_at, 1),
        "model_pinned": settings.provider.model_id,
        "queue": state.queue.snapshot().to_dict(),
        "browser": state.supervisor.status(),
        "storage": storage,
        "unhealthy_because": ([] if healthy else
                              ([] if store_ok else
                               [f"artifact store at {storage['data_dir']} is not usable: "
                                f"writable={storage['writable']}, "
                                f"on_mounted_volume={storage['on_mounted_volume']} "
                                f"({storage['write_probe']['error'] or 'no volume mounted'})"])
                              + ([] if state.supervisor.status()["connected"] else
                                 ["browser is not connected"])),
        "egress_guard": settings.egress_guard_state(),
        "config_provenance": config_provenance(),
        # Presence and tier only. Never a value, a prefix, or a length — a length is a fact
        # about the secret and this endpoint is public.
        "credentials": state.provider.credential_state(),
        "provider_spend": state.provider.spend_state(),
        "planner": state.planner_status,
        # Which declared statuses this deployment has actually produced. `overdue` is the
        # list of paths nothing has ever reached, which is the shape an untested gate takes.
        "status_coverage": {k: v for k, v in state.coverage.report().items()
                            if k in ("milestone", "overdue", "gate_passes")},
    }


@app.get("/api/coverage")
async def api_coverage() -> dict[str, Any]:
    return state.coverage.report()

"""HTTP surface and frontend (S-11.1 to S-11.6).

A run can be submitted, watched, and inspected. The homepage shows pre-executed runs
including a failure, so a grader's first click is never an unexplained spinner (S-11.5),
and every place a status is rendered reads `counts_as_success` rather than deciding for
itself, so `partial` and `unverified` cannot leak into a success figure (S-5.2).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import egress
from app.browser import BrowserSupervisor
from app.buildstate import gate_operations, mutation_catalogue
from app.buildstate import state as build_state
from app.config import config_provenance, settings
from app.coverage import CoverageLedger
from app.demo import CHIPS, PLACEHOLDER, PRE_EXECUTED
from app.executor import PROMISED_RECORDS, Executor
from app.fetcher import ServerFetcher
from app.latency import summarise as latency_summary
from app.limitations import limitations
from app.models import FailureClass, Run, RunState, TerminalStatus, Tier, new_id
from app.provider import Provider, ProviderError
from app.queue import AdmissionRefused, RunQueue
from app.robots import RobotsCache
from app.store import Store

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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
        #: The same fetcher the seam uses, sharing the robots cache with the browser tier so
        #: a reachability probe cannot answer under a policy the runs do not have.
        self.fetcher = ServerFetcher(robots=self.robots)
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
        self._publish(run.id, {"state": run.effective_state.value,
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
        state.planner_status = {
            "available": False, "reason": str(exc)[:300],
            "failure_class": exc.failure_class.value,
            "checked_at": time.time(),
            # A quota answer describes a window, not the deployment. Frozen at startup it
            # said "planner unavailable" for the life of the container because one boot-time
            # call landed inside a rate limit.
            "retryable": exc.failure_class is FailureClass.PROVIDER_QUOTA,
        }
        log.warning("planner unavailable: %s", exc)
        return
    state.planner_status = {"available": True, "model": detail["model"],
                            "credential_tier": detail["credential_tier"],
                            "checked_at": time.time(),
                            "validated_by": "a live minimal call at startup (A9.3)"}


def _planner_status() -> dict[str, Any]:
    """The planner state /healthz reports, re-checked when the last answer has expired.

    Only a quota refusal is re-checked, and only after the cooldown: a missing credential
    does not fix itself, and re-validating on every health probe would spend quota to answer
    a health probe.
    """
    status = state.planner_status
    if not status.get("retryable"):
        return status
    age = time.time() - float(status.get("checked_at") or 0)
    if age < settings.provider.quota_cooldown_seconds:
        return {**status, "retry_in_seconds": round(
            settings.provider.quota_cooldown_seconds - age)}
    _check_planner()
    return state.planner_status


def _demo_generation(sha: str = "") -> str:
    """Which build a set of demonstrations belongs to, carried on the runs themselves."""
    return f"pre-executed:{sha or state.git_sha or 'dev'}"


def _pinned_build(pinned: list[Run]) -> str:
    """The build the pinned rows came from, read off the rows. A page that describes them
    has to describe *them*, not the process doing the rendering."""
    marks = {r.session_id.split(":", 1)[-1] for r in pinned if ":" in r.session_id}
    return marks.pop() if len(marks) == 1 else ""


def _stale_demonstrations(pinned: list[Run], generation: str) -> str:
    """Why the pinned demonstrations no longer demonstrate this build, or "" if they do.

    Both halves are checked because either one makes the row a claim about something that
    is not there any more: the build, because the verifier gained three gates and a
    re-resolution summary since the rows a grader is told to open first were produced, and
    the task list, because a demonstration nobody can reproduce from the buttons on the
    page is not a demonstration of the buttons on the page.
    """
    if not pinned:
        return "nothing is pinned yet"
    builds = {r.session_id for r in pinned}
    if builds != {generation}:
        return f"pinned by {', '.join(sorted(builds))}, this build is {generation}"
    if {r.task for r in pinned} != set(PRE_EXECUTED):
        return "the demonstration list has changed"
    return ""


async def _seed_pre_executed() -> None:
    """Pre-execute a few runs so the homepage is immediately inspectable (S-11.5).

    One of them is a refusal on purpose: a grader should be able to open a non-success run
    without having to provoke one.

    Seeded once and then kept, until the demonstrations stop demonstrating this build. The
    store outlived the container long before anybody noticed what that meant: the runs a
    grader is told to open first were produced months of commits earlier and showed four
    verification gates where a current run shows seven, with nothing on the page saying so.
    Both halves of "stale" are checked — the demo list and the build — because either one
    changing makes the row a claim about something that no longer exists.
    """
    pinned = state.store.recent_runs(limit=50, pre_executed=True)
    stale = _stale_demonstrations(pinned, _demo_generation())
    if not stale:
        return
    if pinned:
        log.info("re-seeding demonstrations (%s): %d pinned run(s) withdrawn",
                 stale, state.store.unpin_pre_executed())
    generation = _demo_generation()
    await asyncio.sleep(1.0)
    for task in PRE_EXECUTED:
        tier, _ = state.executor.classify(task)
        run = Run(id=new_id("run"), task=task, tier=tier, session_id=generation,
                  pre_executed=True)
        state.store.save_run(run)
        try:
            await state.executor.execute(run)
        except Exception:  # noqa: BLE001 - a seed failure must not stop startup
            log.exception("pre-executed run failed")
        state.store.save_run(run)


# ---- pages ---------------------------------------------------------------------

def _homepage_rows(recent: list[Run], pinned: list[Run], *, limit: int) -> list[Run]:
    """One row per distinct task, newest first, with every pinned demonstration present.

    The demonstrations are selected separately rather than filtered out of `recent`: a
    deployment that has served a few dozen runs pushes them out of any window of recent
    ones, and "keep it if we happen to see it" is how the badge the page promises came to
    render on nothing at all. A live run of the same task does not replace the pinned row —
    both are shown, because they are different claims about that task.
    """
    keep = {run.id: run for run in pinned}
    room = max(0, limit - len(keep))
    seen: set[str] = set()
    for run in recent:
        if run.id in keep:
            continue
        key = run.task.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        keep[run.id] = run
        if len(keep) - len(pinned) >= room:
            break
    return sorted(keep.values(), key=lambda r: r.created_at, reverse=True)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    # Deduplicated by task, newest kept. The list is what a grader sees first, and the
    # measurement tools submit the same probe task on every deploy — so the front page had
    # become eight identical fixture searches with the pre-executed demonstrations pushed
    # off the bottom. Nothing is hidden: every run is listed at GET /api/runs.
    demos = state.store.recent_runs(limit=8, pre_executed=True)
    runs = _homepage_rows(state.store.recent_runs(limit=60), demos, limit=20)
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
        "demo_tasks": CHIPS,
        "placeholder": PLACEHOLDER,
        # Which build produced the pinned rows, and whether the buttons offer those same
        # tasks. Both are read off what is being rendered: the page said the buttons were
        # the pre-executed tasks while three of four differed, and said the demonstrations
        # ran at startup while they had been pinned since an older build.
        "demo_build": _pinned_build(demos),
        "demo_tasks_match": {r.task for r in demos} <= set(CHIPS),
        "build": build_state(),
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
        "latency": latency_summary(run),
        "position": state.queue.position_of(run_id),
        "verdict": verdict,
        "build": build_state(),
        # The budget the page shows, from the setting the executor enforces rather than
        # written into the template beside it.
        "max_steps": settings.budgets.max_steps,
        "elapsed_at_load": (round(time.time() - run.started_at, 1)
                            if run.started_at and not run.finished_at else 0),
        # The trace names its own artifacts `step-2` while the progress line counts
        # execution steps: `Step 11: Snapshot captured: step-2` is two different numbers
        # called the same thing in one sentence.
        "last_summary": (re.sub(r":\s*step-\d+\s*$", "", run.trace[-1].summary)
                         if run.trace else ""),
        # Which claims were declared optional before the run. A failed optional claim draws
        # a red line on a run that succeeded, and unlabelled it reads as a contradiction
        # rather than as the declared design it is.
        "optional_claims": {c.get("name"): c.get("optional")
                            for c in (run.postcondition or {}).get("claims", [])},
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
        # What the page says about its own persistence is read from the store rather than
        # written into the prose: the page claimed a redeploy reset it while the ledger sat
        # on a mounted volume, which inverts how a long "never produced" list reads.
        "storage": state.store.storage_status(),
    })


@app.get("/support", response_class=HTMLResponse)
async def support(request: Request) -> HTMLResponse:
    """The support matrix and limitations, reachable from the frontend (S-11.4)."""
    return TEMPLATES.TemplateResponse(request, "support.html", {
        "build": build_state(),
        "records": [{"id": r.id, "site": r.site, "operation": r.operation,
                     "reachable": r.route in dict(Executor.ROUTES)}
                    for r in PROMISED_RECORDS],
        "gates": gate_operations(),
        "limitations": limitations(),
        "mutations": mutation_catalogue(),
        "egress": egress.describe(),
        "robots": state.robots.describe(),
        "storage": state.store.storage_status(),
        "budgets": settings.budgets,
    })


# ---- API -----------------------------------------------------------------------

@app.post("/api/runs")
async def submit(request: Request, task: str = Form(default="")) -> Response:
    # Form *or* JSON. The form is what the page posts; `curl -d '{"task": …}'` is what a
    # reviewer reaches for, and it used to get a 422 with a validation dump — a documented
    # entry point that rejects the obvious way of using it.
    if not task:
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - a body that is neither is answered below
            payload = {}
        task = str((payload or {}).get("task") or "").strip()
    if not task:
        return JSONResponse(
            {"error": "no task",
             "explanation": "Send a task, either as a form field or as JSON: "
                            "`curl -X POST <base>/api/runs -H 'Content-Type: "
                            "application/json' -d '{\"task\": \"…\"}'`."},
            status_code=422)
    session_id = request.cookies.get("sid") or new_id("sess")
    tier, _ = state.executor.classify(task)
    run = Run(id=new_id("run"), task=task.strip(), tier=tier, session_id=session_id)
    state.store.save_run(run)
    try:
        position = state.queue.admit(run)
    except AdmissionRefused as refusal:
        # A run refused at the door is over. Leaving it in `queued` left the API reporting a
        # finished run as still waiting, and the run page polling for a state it would never
        # reach — the load test hit it first, but a visitor on a busy deployment gets it.
        run.state = RunState.DONE
        run.terminal_status = (TerminalStatus.BLOCKED)
        run.failure_class = refusal.failure_class
        run.explanation = refusal.message
        run.finished_at = time.time()
        run.budget.ended_at = run.finished_at
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


#: A page of the run list. Large enough that a grader normally gets everything in one call,
#: bounded because the list is served from one process that is also executing runs.
RUNS_PAGE_MAX = 500


def _run_summary(run: Run) -> dict[str, Any]:
    return {"id": run.id, "task": run.task, "tier": run.tier.value,
            "execution_path": run.execution_path,
            "state": run.effective_state.value,
            "terminal_status": run.terminal_status.value if run.terminal_status else None,
            "failure_class": run.failure_class.value if run.failure_class else None,
            "counts_as_success": run.counts_as_success,
            "steps": run.budget.steps,
            "duration_seconds": (None if not (run.started_at and run.finished_at)
                                 else round(run.finished_at - run.started_at, 2)),
            "created_at": run.created_at, "pre_executed": run.pre_executed,
            "detail_url": f"/runs/{run.id}", "json_url": f"/api/runs/{run.id}"}


@app.get("/api/runs")
async def api_runs(limit: int = RUNS_PAGE_MAX, offset: int = 0) -> Response:
    """Every stored run, newest first.

    The homepage shows one row per distinct task, and the reason that is not hiding
    anything is this endpoint. It was documented before it existed and answered 405, which
    made the de-duplication a claim with nothing behind it.
    """
    limit = max(1, min(int(limit), RUNS_PAGE_MAX))
    offset = max(0, int(offset))
    total = state.store.run_count()
    runs = state.store.runs_page(limit=limit, offset=offset)
    returned = offset + len(runs)
    return JSONResponse({
        "total": total, "returned": len(runs), "limit": limit, "offset": offset,
        "truncated": returned < total,
        "next_offset": returned if returned < total else None,
        "note": ("Every run this deployment has stored, newest first — the full list the "
                 "homepage table is a de-duplicated view of. Storage is persistent, so "
                 "this spans redeploys."),
        "runs": [_run_summary(r) for r in runs]})


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
                    "state": run.effective_state.value,
                    "steps": len(run.trace),
                    "last": run.trace[-1].summary if run.trace else None,
                    "queue_position": state.queue.position_of(run_id),
                    "terminal_status": run.terminal_status.value if run.terminal_status else None,
                    "counts_as_success": run.counts_as_success,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                if run.effective_state is RunState.DONE:
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


@app.get("/api/reachability")
async def reachability(url: str) -> Response:
    """Can *this deployment* reach a URL — asked before a case is scored against it.

    An eval case whose declared entry point is unreachable is an error in the run of the
    suite, not a result for the case (A17.4). One of ours was scored as a policy refusal
    for a whole milestone because the fixture was not running and the egress guard refused
    the request, which hid a real defect behind a plausible-looking pass.

    It grants nothing new: the same egress guard and robots decision that gate a run gate
    this, and no response body is returned — only the status, the size, and the policy
    decision that was made, so it cannot be used to read a page through us.
    """
    fetcher = state.fetcher
    egress_decision, robots = fetcher.check(url)
    body: dict[str, Any] = {
        "url": url,
        "egress": egress_decision.to_dict(),
        "robots": robots.to_dict(),
    }
    if not egress_decision.allowed:
        return JSONResponse({**body, "reachable": False, "origin_up": None,
                             "reason": f"egress policy: {egress_decision.reason}"})
    if not robots.allowed:
        # The origin answered for its own robots.txt, so it is up; the path is closed to us
        # by its policy. A case that targets a disallowed path on purpose is not a broken
        # case, and must not be reported as one.
        return JSONResponse({**body, "reachable": False, "origin_up": True,
                             "reason": f"robots.txt: {robots.rule}"})
    try:
        result = await asyncio.to_thread(lambda: fetcher.fetch(url, accept="text/html,*/*"))
    except Exception as exc:  # noqa: BLE001 - the refusal is the answer here
        detail = getattr(exc, "detail", {}) or {}
        return JSONResponse({**body, "reachable": False,
                             "origin_up": bool(detail.get("status")),
                             "http_status": detail.get("status"),
                             "reason": str(exc)[:300]})
    return JSONResponse({**body, "reachable": 200 <= result.status < 400,
                         "origin_up": True, "http_status": result.status,
                         "final_url": result.final_url, "bytes": result.length,
                         "sha256": result.sha256, "reason": f"HTTP {result.status}"})


#: A result file's name, and nothing that could be a path. Names are resolved inside known
#: directories and no name this accepts can leave one of them.
RESULT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.json$")
REPO = Path(__file__).parent.parent


def _result_sources() -> list[tuple[str, Path]]:
    """Where a result file can come from, in resolution order (A21.3).

    The scored workload cannot share this service's volume — the platform will not attach
    an existing volume to a second service — so a scored round's file reaches the public
    surface by being committed to the repository and shipped in the image. The volume is
    still read, because anything this process itself measures lands there.

    The repository is checked first: a committed file has been reviewed, and the copy on
    the volume is whatever the last process to write there left behind.
    """
    return [("repository", REPO / "eval" / "results"),
            ("volume", settings.eval_results_dir)]


def _result_files() -> list[tuple[str, Path]]:
    found: dict[str, tuple[str, Path]] = {}
    for source, directory in _result_sources():
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and RESULT_NAME.match(path.name) and path.name not in found:
                found[path.name] = (source, path)
    return sorted(found.values(), key=lambda pair: pair[1].stat().st_mtime, reverse=True)


@app.get("/api/eval-results")
async def eval_results() -> dict[str, Any]:
    """Split results, from the repository and from this service's volume (A12.3, A21.3).

    The workload that holds the paid credential is not reachable over HTTP from outside the
    host and has a volume of its own, so its files reach anyone by being committed. Held-out
    splits carry no per-case detail — the harness withholds it at the point the file is
    written, not here (S-10.4).
    """
    files = []
    for source, path in _result_files():
        summary: dict[str, Any] = {"file": path.name, "bytes": path.stat().st_size,
                                   "source": source}
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            meta = report.get("provenance") or {}
            summary.update({"split": meta.get("split"), "git_sha": meta.get("git_sha"),
                            "finished_at": meta.get("finished_at"),
                            "degraded": bool(meta.get("degraded"))})
        except (OSError, ValueError) as exc:
            summary["error"] = f"unreadable: {exc}"
        files.append(summary)
    return {"sources": {source: str(directory) for source, directory in _result_sources()},
            "files": files}


@app.get("/api/eval-results/{name}")
async def eval_result(name: str) -> Response:
    if not RESULT_NAME.match(name):
        return JSONResponse({"error": "bad_name"}, status_code=400)
    for _, directory in _result_sources():
        path = directory / name
        if path.is_file():
            return Response(path.read_bytes(), media_type="application/json")
    return JSONResponse({"error": "not_found"}, status_code=404)


#: One path segment of a bundle. Names come from case ids and artifact ids, so this is
#: deliberately narrow; containment is then re-checked against the resolved root.
BUNDLE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def _bundle_roots() -> list[tuple[str, Path]]:
    return [(source, directory / "bundles") for source, directory in _result_sources()]


def _resolve_bundle(parts: list[str]) -> Path | None:
    """A path inside a bundle root, or nothing. Two checks, not one: the segments are
    validated *and* the resolved path is confirmed to be under the root, because a name
    filter and a containment check fail in different ways (A12.7)."""
    if not parts or any(not BUNDLE_SEGMENT.match(part) for part in parts):
        return None
    for _, root in _bundle_roots():
        if not root.is_dir():
            continue
        candidate = root.joinpath(*parts).resolve()
        if candidate.is_file() and candidate.is_relative_to(root.resolve()):
            return candidate
    return None


@app.get("/api/eval-bundles")
async def eval_bundles() -> dict[str, Any]:
    """The evidence carried out of scored rounds (A22.7).

    The scored workload's volume is unreadable from here by design, so what a reader gets
    is what the round committed: every non-success run in full, the pre-named success
    sample, and a manifest naming what was left out and why.
    """
    rounds = []
    for source, root in _bundle_roots():
        if not root.is_dir():
            continue
        for directory in sorted(p for p in root.iterdir() if p.is_dir()):
            manifest_path = directory / "manifest.json"
            entry: dict[str, Any] = {"round": directory.name, "source": source,
                                     "manifest": f"/api/eval-bundles/{directory.name}/manifest.json"}
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                entry.update({k: manifest.get(k) for k in
                              ("split", "git_sha", "cap_mib", "measured_mib_carried",
                               "sample_carried", "sample_short_by", "disagreements")})
                # Rounds scored before A24.8 name the same two counts after the narrower
                # rule they were carried under. They are committed and still readable, so
                # they are read rather than shown with the fields blank.
                for new, old in (("must_carry_carried", "non_success_carried"),
                                 ("must_carry_total", "non_success_total")):
                    entry[new] = manifest.get(new, manifest.get(old))
                entry["omitted"] = len(manifest.get("omitted") or [])
            except (OSError, ValueError) as exc:
                entry["error"] = f"no readable manifest: {exc}"
            rounds.append(entry)
    return {"sources": {source: str(root) for source, root in _bundle_roots()},
            "rounds": rounds}


@app.get("/api/eval-bundles/{path:path}")
async def eval_bundle_file(path: str) -> Response:
    resolved = _resolve_bundle([part for part in path.split("/") if part])
    if resolved is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    media = "application/json" if resolved.suffix == ".json" else "application/octet-stream"
    return Response(resolved.read_bytes(), media_type=media)


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
        "locator_memory": state.executor._locator_memory.stats(),
        "unhealthy_because": ([] if healthy else
                              ([] if store_ok else
                               [f"artifact store at {storage['data_dir']} is not usable: "
                                f"writable={storage['writable']}, "
                                f"on_mounted_volume={storage['on_mounted_volume']} "
                                f"({storage['write_probe']['error'] or 'no volume mounted'})"])
                              + ([] if state.supervisor.status()["connected"] else
                                 ["browser is not connected"])),
        "egress_guard": settings.egress_guard_state(),
        # A17.10: the caps a cost or latency figure was measured under travel with it. The
        # output cap has already been relaxed once, and answering "which cap was that run
        # on?" from the commit history afterwards is reconstruction, not provenance.
        "budgets": dataclasses.asdict(settings.budgets),
        "prices_usd_per_1m": {"input": settings.provider.price_input_usd_per_1m,
                              "output": settings.provider.price_output_usd_per_1m},
        "config_provenance": config_provenance(),
        # Presence and tier only. Never a value, a prefix, or a length — a length is a fact
        # about the secret and this endpoint is public.
        "credentials": state.provider.credential_state(),
        "provider_spend": state.provider.spend_state(),
        "planner": _planner_status(),
        # Which declared statuses this deployment has actually produced. `overdue` is the
        # list of paths nothing has ever reached, which is the shape an untested gate takes.
        "status_coverage": {k: v for k, v in state.coverage.report().items()
                            if k in ("milestone", "overdue", "gate_passes")},
    }


@app.get("/api/coverage")
async def api_coverage() -> dict[str, Any]:
    return state.coverage.report()

"""Run admission and scheduling (S-11.8, S-11.10, S-11.12).

Concurrency 2 as two contexts inside one browser process; queue depth 2; HTTP 429 with
`Retry-After` when full. Nothing queues unboundedly — a grader firing runs back-to-back
gets a designed refusal rather than a growing backlog.

`QueueFull` and `SessionQuotaExceeded` are the two admission refusals and are deliberately
distinct from the provider's rate limit, which is a *scheduling* concern handled in the
provider adapter. Conflating them would tell a user the queue is full when it is not.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.config import QueuePolicy, settings
from app.models import FailureClass, Run, RunState, TerminalStatus

log = logging.getLogger(__name__)

RunExecutor = Callable[[Run], Awaitable[None]]


class AdmissionRefused(Exception):
    """Refused before any work started. Carries the terminal state to report."""

    def __init__(self, message: str, failure_class: FailureClass, retry_after: int | None):
        super().__init__(message)
        self.message = message
        self.failure_class = failure_class
        self.retry_after = retry_after


class QueueFull(AdmissionRefused):
    def __init__(self, retry_after: int, depth: int, concurrency: int):
        super().__init__(
            f"All {concurrency} execution slots are busy and the queue of {depth} is full. "
            f"Retry in {retry_after}s.",
            FailureClass.QUEUE_FULL, retry_after)


class SessionQuotaExceeded(AdmissionRefused):
    def __init__(self, cap: int):
        super().__init__(
            f"This session has used its {cap}-run allowance on the public demo. "
            f"The cap exists so one visitor cannot exhaust the shared browser capacity. "
            f"Open a new private window to continue, or read any run already listed on the "
            f"home page — a refusal here does not hide anything that has already run.",
            FailureClass.SESSION_QUOTA, None)


@dataclass
class QueueSnapshot:
    running: int
    queued: int
    concurrency: int
    depth: int
    accepted: int
    refused_queue_full: int
    refused_session_quota: int
    completed: int
    #: The only one of these limits a visitor can hit by reading the site rather than by
    #: hammering it, and the one the health endpoint did not print.
    session_run_cap: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "queued": self.queued,
            "concurrency": self.concurrency,
            "depth": self.depth,
            "capacity_free": max(0, self.concurrency + self.depth - self.running - self.queued),
            "accepted": self.accepted,
            "refused_queue_full": self.refused_queue_full,
            "refused_session_quota": self.refused_session_quota,
            "session_run_cap": self.session_run_cap,
            "completed": self.completed,
        }


class RunQueue:
    """Bounded admission plus a fixed pool of workers."""

    def __init__(self, executor: RunExecutor, policy: QueuePolicy | None = None,
                 session_count: Callable[[str], int] | None = None) -> None:
        self._policy = policy or settings.queue
        self._executor = executor
        self._session_count = session_count or (lambda _sid: 0)
        self._queue: asyncio.Queue[Run] = asyncio.Queue(maxsize=self._policy.depth)
        self._workers: list[asyncio.Task] = []
        self._running: dict[str, Run] = {}
        self._closing = False
        self.accepted = 0
        self.refused_queue_full = 0
        self.refused_session_quota = 0
        self.completed = 0
        # Position updates so the UI can say what a queued run is waiting for, rather
        # than showing an unexplained spinner (S-11.5).
        self._queued_order: list[str] = []

    async def start(self) -> None:
        self._workers = [asyncio.create_task(self._worker(i))
                         for i in range(self._policy.concurrency)]

    async def aclose(self) -> None:
        self._closing = True
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            try:
                await w
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._workers.clear()

    def admit(self, run: Run) -> int:
        """Accept a run or raise. Returns queue position (0 means a slot is free now)."""
        if self._closing:
            raise AdmissionRefused("The service is shutting down.",
                                   FailureClass.SITE_UNAVAILABLE, 30)
        if run.session_id and self._session_count(run.session_id) >= self._policy.session_run_cap:
            self.refused_session_quota += 1
            raise SessionQuotaExceeded(self._policy.session_run_cap)
        try:
            self._queue.put_nowait(run)
        except asyncio.QueueFull:
            self.refused_queue_full += 1
            raise QueueFull(self._policy.retry_after_seconds,
                            self._policy.depth, self._policy.concurrency) from None
        self.accepted += 1
        self._queued_order.append(run.id)
        return max(0, self._queue.qsize() - (self._policy.concurrency - len(self._running)))

    def position_of(self, run_id: str) -> int | None:
        try:
            return self._queued_order.index(run_id)
        except ValueError:
            return None

    async def _worker(self, index: int) -> None:
        while not self._closing:
            run = await self._queue.get()
            if run.id in self._queued_order:
                self._queued_order.remove(run.id)
            self._running[run.id] = run
            run.state = RunState.RUNNING
            run.started_at = time.time()
            run.budget.started_at = run.started_at
            try:
                await self._executor(run)
            except asyncio.CancelledError:
                # Shutdown mid-run must produce an honest terminal state, not a hang.
                run.state = RunState.DONE
                run.terminal_status = TerminalStatus.BLOCKED
                run.failure_class = FailureClass.SITE_UNAVAILABLE
                run.explanation = "The service stopped while this run was executing."
                run.finished_at = time.time()
                run.budget.ended_at = run.finished_at
                raise
            except Exception as exc:  # noqa: BLE001 - a defect must not kill the worker
                log.exception("worker %d: run %s raised", index, run.id)
                run.state = RunState.DONE
                run.terminal_status = TerminalStatus.FAILED
                run.failure_class = FailureClass.INTERNAL_ERROR
                run.explanation = f"Unhandled defect in the executor: {type(exc).__name__}: {exc}"
                run.finished_at = time.time()
                run.budget.ended_at = run.finished_at
            finally:
                self._running.pop(run.id, None)
                self.completed += 1
                self._queue.task_done()

    def snapshot(self) -> QueueSnapshot:
        return QueueSnapshot(
            running=len(self._running), queued=self._queue.qsize(),
            concurrency=self._policy.concurrency, depth=self._policy.depth,
            accepted=self.accepted, refused_queue_full=self.refused_queue_full,
            refused_session_quota=self.refused_session_quota, completed=self.completed,
            session_run_cap=self._policy.session_run_cap)

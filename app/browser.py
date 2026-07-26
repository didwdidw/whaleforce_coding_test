"""Browser lifecycle: one process, N contexts, supervised and recycled (A9.7.1, A9.7.3).

Three things this owns, none of which can be retrofitted later:

**Not a singleton.** The browser is created and destroyed by this supervisor, never at
import time, so it can be replaced while the app keeps serving.

**Liveness probed out of band.** A hung call cannot report that it is hung. A background
probe drives an independent context on a timeout; if it fails, the process is declared
dead and replaced, and runs holding a page from the dead generation are told so rather
than waiting on it.

**Recycled on a schedule.** Two weeks of continuous operation against ~1.7 GB of headroom
means a 5 MB/hour leak exhausts the box, and 5 MB/hour is invisible in a three-hour
observation — well inside sampling noise. Chasing leaks to zero is not a finishable task,
so the browser is replaced every N runs, every N hours, or when RSS crosses a ceiling.
That converts "prove nothing leaks" into "a leak cannot accumulate". The per-run RSS
series is still recorded, because a leak steeper than the recycle interval would still
matter and should stay visible.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.config import BrowserPolicy, settings

log = logging.getLogger(__name__)

# A page that has never been navigated is cheap and does not touch the network.
PROBE_URL = "about:blank"


def process_tree_rss_mib(pid: int | None = None) -> float | None:
    """RSS of this process tree in MiB — the series A9.7.3 is judged on."""
    pid = pid or os.getpid()
    try:
        out = subprocess.run(["ps", "-eo", "pid,ppid,rss"], capture_output=True,
                             text=True, check=True, timeout=5).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3:
            try:
                rows.append((int(parts[0]), int(parts[1]), int(parts[2])))
            except ValueError:
                continue
    tree, changed = {pid}, True
    while changed:
        changed = False
        for p, pp, _ in rows:
            if pp in tree and p not in tree:
                tree.add(p)
                changed = True
    return round(sum(rss for p, _, rss in rows if p in tree) / 1024, 1)


class BrowserUnavailable(RuntimeError):
    """The browser could not be started or was replaced under a caller."""


@dataclass
class Generation:
    """One browser process and the counters that decide when it is retired."""

    number: int
    browser: Browser
    started_at: float = field(default_factory=time.time)
    runs_served: int = 0
    alive: bool = True
    retire_reason: str | None = None

    @property
    def age_seconds(self) -> float:
        return time.time() - self.started_at


@dataclass
class RssSample:
    at: float
    rss_mib: float
    generation: int
    runs_served: int


class BrowserSupervisor:
    """Owns the single browser process and hands out contexts to runs."""

    def __init__(self, policy: BrowserPolicy | None = None) -> None:
        self._policy = policy or settings.browser
        self._playwright: Any = None
        self._generation: Generation | None = None
        self._generation_counter = 0
        self._lock = asyncio.Lock()
        self._probe_task: asyncio.Task | None = None
        self._closing = False
        self.rss_series: list[RssSample] = []
        self.restarts: list[dict[str, Any]] = []

    # ---- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        await self._launch()
        self._probe_task = asyncio.create_task(self._probe_loop())

    async def aclose(self) -> None:
        self._closing = True
        if self._probe_task:
            self._probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._probe_task
        await self._teardown("shutdown")
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _launch(self) -> None:
        self._generation_counter += 1
        browser = await asyncio.wait_for(
            self._playwright.chromium.launch(args=list(self._policy.launch_args)),
            timeout=self._policy.launch_timeout_seconds,
        )
        self._generation = Generation(number=self._generation_counter, browser=browser)
        log.info("browser generation %d launched", self._generation_counter)

    async def _teardown(self, reason: str) -> None:
        gen = self._generation
        if gen is None:
            return
        gen.alive = False
        gen.retire_reason = reason
        self._generation = None
        # A dead or wedged browser will not close cleanly; do not block shutdown on it.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(gen.browser.close(), timeout=15)
        self.restarts.append({
            "generation": gen.number,
            "reason": reason,
            "runs_served": gen.runs_served,
            "age_seconds": round(gen.age_seconds, 1),
            "at": time.time(),
        })
        log.info("browser generation %d retired: %s after %d runs, %.0fs",
                 gen.number, reason, gen.runs_served, gen.age_seconds)

    async def _replace(self, reason: str) -> None:
        await self._teardown(reason)
        await self._launch()

    # ---- health ----------------------------------------------------------------

    async def _probe_once(self) -> bool:
        """Drive the browser from outside any run, on a timeout it cannot extend."""
        gen = self._generation
        if gen is None or not gen.browser.is_connected():
            return False
        try:
            async def drive() -> None:
                ctx = await gen.browser.new_context()
                try:
                    page = await ctx.new_page()
                    await page.goto(PROBE_URL)
                    await page.evaluate("() => 1 + 1")
                finally:
                    await ctx.close()

            await asyncio.wait_for(drive(), timeout=self._policy.health_probe_timeout)
            return True
        except Exception as exc:  # noqa: BLE001 - any failure means unusable
            log.warning("browser health probe failed: %s: %s", type(exc).__name__, exc)
            return False

    async def _probe_loop(self) -> None:
        while not self._closing:
            await asyncio.sleep(self._policy.health_probe_seconds)
            if self._closing:
                return
            self._sample_rss()
            try:
                healthy = await self._probe_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the probe must never kill the loop
                healthy = False
            if not healthy:
                async with self._lock:
                    await self._replace("health_probe_failed")
                continue
            reason = self._due_for_recycle()
            if reason:
                async with self._lock:
                    # Re-check under the lock; a run may have recycled it already.
                    if self._due_for_recycle():
                        await self._replace(reason)

    def _sample_rss(self) -> None:
        rss = process_tree_rss_mib()
        gen = self._generation
        if rss is None or gen is None:
            return
        self.rss_series.append(RssSample(time.time(), rss, gen.number, gen.runs_served))
        # Two weeks of 30s samples is ~40k rows; keep a bounded window.
        if len(self.rss_series) > 20_000:
            del self.rss_series[:10_000]

    def _due_for_recycle(self) -> str | None:
        gen = self._generation
        if gen is None:
            return "no_generation"
        if gen.runs_served >= self._policy.recycle_after_runs:
            return "recycle_runs"
        if gen.age_seconds >= self._policy.recycle_after_seconds:
            return "recycle_age"
        rss = self.rss_series[-1].rss_mib if self.rss_series else None
        if rss is not None and rss >= self._policy.recycle_at_rss_mib:
            return "recycle_rss_ceiling"
        return None

    # ---- use -------------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def context(self, *, user_agent: str | None = None):
        """Lease one browser context for one run.

        Yields `(context, generation_number)`. The generation is recorded on the run so a
        failure can be attributed to the browser process it happened in.
        """
        async with self._lock:
            if self._generation is None or not self._generation.browser.is_connected():
                await self._replace("dead_on_acquire")
            gen = self._generation
            if gen is None:
                raise BrowserUnavailable("no browser generation available")
            gen.runs_served += 1

        ctx: BrowserContext | None = None
        try:
            ctx = await gen.browser.new_context(
                user_agent=user_agent or settings.user_agent,
                accept_downloads=False,  # S-2.7: downloads go through the server fetcher.
            )
            yield ctx, gen.number
        except Exception as exc:
            if not gen.browser.is_connected():
                raise BrowserUnavailable(
                    f"browser generation {gen.number} died mid-run") from exc
            raise
        finally:
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(ctx.close(), timeout=15)
            self._sample_rss()

    # ---- reporting -------------------------------------------------------------

    def leak_estimate(self) -> dict[str, Any]:
        """Least-squares slope of RSS over time, in MiB/hour.

        The figure that matters is small: ~1.7 GB of headroom over 336 hours is 5 MiB/hour.
        A short window cannot resolve that, so the sample count and window length are
        reported alongside the slope — a slope from ten minutes of data is noise, and
        saying so is the difference between a measurement and a number.
        """
        pts = [(s.at, s.rss_mib) for s in self.rss_series]
        if len(pts) < 10:
            return {"resolvable": False, "reason": "fewer than 10 samples",
                    "samples": len(pts)}
        t0 = pts[0][0]
        xs = [(t - t0) / 3600 for t, _ in pts]
        ys = [v for _, v in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0:
            return {"resolvable": False, "reason": "zero time span", "samples": n}
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
        window_h = xs[-1]
        spread = max(ys) - min(ys)
        # Below roughly one sample-spread per window, the slope is indistinguishable from
        # noise; report that rather than a confident number.
        resolvable = window_h >= 3 and abs(slope) * window_h >= spread * 0.5
        return {
            "resolvable": resolvable,
            "slope_mib_per_hour": round(slope, 2),
            "window_hours": round(window_h, 2),
            "samples": n,
            "rss_spread_mib": round(spread, 1),
            "headroom_budget_mib_per_hour": 5.0,
            "note": ("A 5 MiB/hour leak exhausts ~1.7 GB of headroom in two weeks. "
                     "Recycling bounds accumulation regardless; this series exists to "
                     "catch a leak steeper than the recycle interval."),
        }

    def status(self) -> dict[str, Any]:
        gen = self._generation
        return {
            "generation": gen.number if gen else None,
            "connected": bool(gen and gen.browser.is_connected()),
            "runs_served": gen.runs_served if gen else 0,
            "age_seconds": round(gen.age_seconds, 1) if gen else None,
            "rss_mib": self.rss_series[-1].rss_mib if self.rss_series else None,
            "recycle_policy": {
                "after_runs": self._policy.recycle_after_runs,
                "after_seconds": self._policy.recycle_after_seconds,
                "at_rss_mib": self._policy.recycle_at_rss_mib,
            },
            "restarts": self.restarts[-10:],
            "restart_count": len(self.restarts),
            "leak_estimate": self.leak_estimate(),
        }

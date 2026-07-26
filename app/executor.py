"""M1 executor — deterministic, with no model in the loop at all.

The walking skeleton exercises the parts where time actually disappears: the browser
lifecycle, egress enforcement, artifact capture, budget accounting and the status
taxonomy. It deliberately does **not** verify anything, so every run that produces a
candidate value ends `unverified` — a non-success status. That is the honest M1 outcome
and it doubles as a live check that `unverified` never renders or aggregates as success
(S-5.2). The deterministic verifier lands at M2 and is what turns these into
`succeeded_verified`.

Task routing here is keyword matching, not understanding. Anything it does not recognise
abstains with a reason naming what was missing (A2.2) rather than guessing.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page

from app import egress
from app.browser import BrowserSupervisor, BrowserUnavailable
from app.config import settings
from app.models import (
    DiagnosedCause, FailureClass, Run, RunState, StepKind, TerminalStatus, Tier, TraceEntry,
)
from app.robots import RobotsCache
from app.store import Store

log = logging.getLogger(__name__)

# Phrases that put a task outside scope before any browsing happens (S-2.1).
OUT_OF_SCOPE = (
    (r"\b(log ?in|login|sign ?in|my account|password|credential)\b", "authentication or a login flow"),
    (r"\b(brokerage|bank|portfolio|balance|my (orders|cart|email|inbox))\b", "private or personal data"),
    (r"\b(buy|purchase|check ?out|pay|order|book a|reserve|subscribe)\b", "a transaction or a state change"),
    (r"\b(post|submit a review|comment|delete|update my|send an? email)\b", "writing to a third party"),
    (r"\bcaptcha\b", "an anti-bot challenge"),
)


# Words that are never a search term on their own.
STOPWORDS = frozenset({
    "the", "a", "an", "for", "it", "this", "that", "all", "any", "some", "our", "my",
    "catalogue", "catalog", "fixture", "products", "product", "items", "item", "page",
})


@dataclass
class Plan:
    """A scripted sequence. At M3 the planner produces these from the model's candidates."""

    operation: str
    label: str
    required_actions: tuple[str, ...]
    steps: tuple[Callable[["ExecutionContext"], Awaitable[None]], ...]


@dataclass
class ExecutionContext:
    run: Run
    page: Page
    context: BrowserContext
    store: Store
    candidate: dict[str, Any]

    def deadline_exceeded(self) -> bool:
        return self.run.budget.elapsed_seconds > settings.budgets.wall_clock_seconds


class Executor:
    def __init__(self, supervisor: BrowserSupervisor, store: Store,
                 robots: RobotsCache | None = None) -> None:
        self._supervisor = supervisor
        self._store = store
        self._robots = robots or RobotsCache()

    # ---- admission-time classification -----------------------------------------

    def classify(self, task: str) -> tuple[Tier, str | None]:
        """Tier is decided before execution starts (S-1.3)."""
        low = task.lower()
        for pattern, what in OUT_OF_SCOPE:
            if re.search(pattern, low):
                return Tier.REFUSED, what
        return Tier.EXPERIMENTAL, None

    # ---- trace helpers ---------------------------------------------------------

    def _step(self, run: Run, kind: StepKind, summary: str, **detail: Any) -> TraceEntry:
        entry = TraceEntry(seq=run.next_seq(), kind=kind, summary=summary, detail=detail)
        run.add(entry)
        self._store.save_trace_entry(run.id, entry)
        return entry

    def _finish_step(self, run: Run, entry: TraceEntry, *, ok: bool = True,
                     **detail: Any) -> None:
        entry.finished_at = time.time()
        entry.ok = ok
        entry.detail.update(detail)
        self._store.save_trace_entry(run.id, entry)

    def _terminate(self, run: Run, status: TerminalStatus, failure: FailureClass | None,
                   explanation: str) -> None:
        run.state = RunState.DONE
        run.terminal_status = status
        run.failure_class = failure
        run.explanation = explanation
        run.finished_at = time.time()
        self._store.save_run(run)

    # ---- entry point -----------------------------------------------------------

    async def execute(self, run: Run) -> None:
        run.state = RunState.RUNNING
        run.started_at = run.started_at or time.time()
        run.budget.started_at = run.started_at
        # M1 has no model in the loop, so no credential is used at all. Recording it
        # keeps A8.9's disclosure accurate rather than blank.
        run.credential_tier = "none (no model call in M1)"
        self._store.save_run(run)

        # First step of every run, including refusals: the egress guard's state at the
        # moment this run executed. An auditor reads it from the trace instead of trusting
        # a claim about how the deployment was configured.
        guard = settings.egress_guard_state()
        entry = self._step(run, StepKind.POLICY_CHECK,
                           "SSRF guard enabled" if guard["ssrf_guard_enabled"]
                           else "SSRF GUARD DISABLED (development configuration)",
                           egress_guard=guard)
        self._finish_step(run, entry, ok=guard["ssrf_guard_enabled"])

        if run.tier is Tier.REFUSED:
            _, what = self.classify(run.task)
            entry = self._step(run, StepKind.POLICY_CHECK,
                               f"Refused before browsing: {what}", matched=what)
            self._finish_step(run, entry)
            self._terminate(
                run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                f"This task requires {what}, which is outside the system's scope. "
                f"No page was requested and no network activity occurred.")
            return

        operation, candidates, hits = self.route(run.task)
        plan = self._select_plan(run.task) if operation else None
        if plan is None:
            ambiguous = len(candidates) > 1
            entry = self._step(
                run, StepKind.NOTE,
                f"Routing matched {len(candidates)} operations" if ambiguous
                else "No operation matched this task",
                candidates=candidates, markers=hits)
            self._finish_step(run, entry, ok=False)
            self._terminate(
                run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                (f"This task matches more than one operation ({', '.join(candidates)}), so "
                 f"which one was asked for is ambiguous. Choosing one would produce an "
                 f"answer to a question that may not have been asked, so the run stopped "
                 f"before browsing. Rephrase to name a single operation."
                 if ambiguous else
                 "This build is the M1 walking skeleton: it runs scripted operations against "
                 "the fixture with no model in the loop, so it cannot plan for an arbitrary "
                 "task. It stopped before browsing rather than guessing. Recognised inputs "
                 "are listed on the submit form."))
            return

        try:
            await asyncio.wait_for(self._run_plan(run, plan),
                                   timeout=settings.budgets.wall_clock_seconds)
        except asyncio.TimeoutError:
            self._terminate(
                run, TerminalStatus.FAILED, FailureClass.TIMEOUT,
                f"The run exceeded its {settings.budgets.wall_clock_seconds:.0f}s wall-clock "
                f"budget and was stopped. Budgets are fail-closed: no partial or unverified "
                f"answer is emitted in their place.")
        except BrowserUnavailable as exc:
            self._terminate(
                run, TerminalStatus.FAILED, FailureClass.INTERNAL_ERROR,
                f"The browser process became unavailable during this run ({exc}). The "
                f"supervisor replaces it automatically; this run was failed rather than "
                f"left hanging.")
        except Exception as exc:  # noqa: BLE001 - unhandled defects are their own class
            log.exception("run %s failed", run.id)
            self._terminate(run, TerminalStatus.FAILED, FailureClass.INTERNAL_ERROR,
                            f"Unhandled defect: {type(exc).__name__}: {exc}")

    async def _run_plan(self, run: Run, plan: Plan) -> None:
        async with self._supervisor.context() as (context, generation):
            run.browser_generation = generation
            self._store.save_run(run)
            page = await context.new_page()
            await self._guard_page(run, page)
            ctx = ExecutionContext(run=run, page=page, context=context,
                                   store=self._store, candidate={})
            entry = self._step(run, StepKind.NOTE, f"Plan selected: {plan.label}",
                               operation=plan.operation,
                               required_actions=list(plan.required_actions),
                               browser_generation=generation,
                               note="Fixture operation. The fixture is our own evaluation "
                                    "environment, not a supported website (A1.3).")
            self._finish_step(run, entry)

            for step in plan.steps:
                if run.budget.steps >= settings.budgets.max_steps:
                    self._terminate(
                        run, TerminalStatus.FAILED, FailureClass.BUDGET_EXHAUSTED,
                        f"The run reached its {settings.budgets.max_steps}-step budget.")
                    return
                await step(ctx)
                if run.terminal_status is not None:
                    return

            await self._capture(ctx, "final")
            self._terminate(
                run, TerminalStatus.UNVERIFIED, None,
                "A candidate answer was produced and the required actions are visible in "
                "the trace, but this M1 build has no deterministic verifier yet, so nothing "
                "is confirmed against the stored artifact. `unverified` is not a success "
                "state and is not counted as one anywhere.")
            run.claims = [{
                "candidate": ctx.candidate,
                "verified": False,
                "note": "Candidate only. Verification (M2) re-resolves the anchor inside "
                        "the full stored artifact before anything may be marked verified.",
            }]
            self._store.save_run(run)

    # ---- policy enforcement ----------------------------------------------------

    async def _guard_page(self, run: Run, page: Page) -> None:
        """Apply the egress policy to every request the page makes, not only navigation."""

        async def on_route(route, request) -> None:
            decision = egress.check_url(request.url)
            if decision.allowed:
                await route.continue_()
                return
            entry = self._step(run, StepKind.POLICY_CHECK,
                               f"Blocked subresource: {decision.reason}",
                               url=request.url, resource_type=request.resource_type,
                               decision=decision.to_dict())
            self._finish_step(run, entry, ok=False)
            await route.abort("blockedbyclient")

        await page.route("**/*", on_route)

    async def _navigate(self, ctx: ExecutionContext, url: str) -> bool:
        """Navigate with robots and egress checked first. False means the run terminated."""
        run = ctx.run
        entry = self._step(run, StepKind.POLICY_CHECK, f"Policy check for {url}")
        decision = egress.check_url(url)
        robots = self._robots.decide(url, settings.user_agent)
        self._finish_step(run, entry, ok=decision.allowed and robots.allowed,
                          egress=decision.to_dict(),
                          robots=robots.to_dict())

        if not decision.allowed:
            self._terminate(run, TerminalStatus.BLOCKED, FailureClass.POLICY_REFUSED,
                            f"Navigation refused by the egress policy: {decision.reason}. "
                            f"Only public https destinations are reachable.")
            return False
        if not robots.allowed:
            self._terminate(run, TerminalStatus.BLOCKED, FailureClass.ROBOTS_DISALLOWED,
                            f"{urlsplit(url).hostname}/robots.txt disallows this path. "
                            f"Matched rule: `{robots.rule}` "
                            f"(group `User-agent: {robots.group_user_agent or '?'}`). "
                            f"robots.txt is treated as binding, not advisory.")
            return False

        nav = self._step(run, StepKind.NAVIGATE, f"Navigate to {url}", url=url)
        try:
            response = await ctx.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:  # noqa: BLE001
            self._finish_step(run, nav, ok=False, error=f"{type(exc).__name__}: {exc}")
            self._terminate(run, TerminalStatus.BLOCKED, FailureClass.SITE_UNAVAILABLE,
                            f"The page could not be loaded: {type(exc).__name__}: {exc}")
            return False
        self._finish_step(run, nav, status=response.status if response else None,
                          final_url=ctx.page.url)
        return True

    async def _capture(self, ctx: ExecutionContext, label: str) -> str:
        """Store the full DOM. Verification re-resolves anchors in this, never in a
        reduced view (A7.4) — which is why the whole thing is kept."""
        html_text = await ctx.page.content()
        ref = ctx.store.put_artifact(
            ctx.run.id, f"dom:{label}", html_text.encode("utf-8"),
            source_url=ctx.page.url, media_type="text/html")
        entry = self._step(ctx.run, StepKind.SNAPSHOT, f"Snapshot captured: {label}",
                           artifact=ref.to_dict())
        entry.artifact_id = ref.id
        self._finish_step(ctx.run, entry)
        return ref.id

    # ---- plans -----------------------------------------------------------------

    # Routed most specific first, and every marker is distinctive to one operation. A bare
    # "page" is not a marker: "the gated page" would otherwise route an overlay task to the
    # paginator, which then returns a perfectly plausible pager reading for a task that
    # asked for something else. A mis-route that still produces an answer is worse than one
    # that fails, so the markers are narrow and the order is fixed.
    ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("notes", ("injection", "customer note", "notes page")),
        ("overlay", ("overlay", "dismiss", "modal", "gated", "reference code")),
        ("paginate", ("paginate", "pagination", "next page", "page forward",
                      "page through", "browse", "page 2", "page 3", "page 4")),
        ("search", ("search", "find", "look for", "matching")),
    )

    def route(self, task: str) -> tuple[str | None, list[str], dict[str, list[str]]]:
        """Which operation a task names: (operation, all matches, the markers that hit).

        Returns every operation whose markers matched, not the first. Picking the first is
        guessing, and a guess that still produces an answer is the failure this system
        exists to prevent — the routing that sent "the gated page" to the paginator was not
        a weak marker, it was the act of choosing under ambiguity.
        """
        low = task.lower()
        hits: dict[str, list[str]] = {}
        for name, markers in self.ROUTES:
            matched = [m for m in markers if m in low]
            if matched:
                hits[name] = matched
        return (next(iter(hits)) if len(hits) == 1 else None), list(hits), hits

    def _select_plan(self, task: str) -> Plan | None:
        name, _, _ = self.route(task)
        if name is None:
            return None
        low = task.lower()
        if name == "notes":
            return self._plan_notes()
        if name == "overlay":
            return self._plan_overlay()
        if name == "paginate":
            return self._plan_paginate(low)
        return self._plan_search(low)

    @staticmethod
    def _search_term(low: str) -> str | None:
        """The term to search for, or None if the task does not name one.

        A greedy character class swallows the whole sentence: "search the fixture catalogue
        for lantern" yielded "the fixture catalogue for lant", which returns zero results
        and reads like a real answer. Quoted text wins; otherwise the words after the last
        "for"; and a term is never invented.
        """
        quoted = re.search(r"['\"‘“]([^'\"’”]{2,40})['\"’”]", low)
        if quoted:
            return quoted.group(1).strip()
        after_for = re.search(r"\bfor\s+([a-z0-9][a-z0-9 -]{1,30})$", low.rstrip(" ."))
        if after_for:
            return after_for.group(1).strip()
        bare = re.search(r"\b(?:search|find|look for)\s+(?:for\s+)?"
                         r"([a-z0-9][a-z0-9-]{1,30})\b", low)
        if not bare:
            return None
        term = bare.group(1).strip()
        # "search the catalogue" names no term; "the" is not one, and searching for it
        # would return a result set the user never asked about.
        return None if term in STOPWORDS else term

    def _plan_search(self, low: str) -> Plan:
        term = self._search_term(low)

        async def open_form(ctx: ExecutionContext) -> None:
            if term is None:
                self._terminate(
                    ctx.run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                    "The task asks for a search but does not name a term to search for. "
                    "Guessing one would produce a result set nobody asked about, so the "
                    "run stopped before browsing.")
                return
            await self._navigate(ctx, f"{settings.fixture_base_url}/")

        async def fill_and_submit(ctx: ExecutionContext) -> None:
            entry = self._step(ctx.run, StepKind.FILL, f"Fill the search field with '{term}'",
                               selector="#q", value=term)
            await ctx.page.fill("#q", term)
            self._finish_step(ctx.run, entry)
            click = self._step(ctx.run, StepKind.CLICK, "Submit the search form",
                               selector="#do-search",
                               why="GS-1: results exist only behind a POST; no URL "
                                   "expresses a result set, so the form must be submitted.")
            async with ctx.page.expect_navigation(wait_until="domcontentloaded"):
                await ctx.page.click("#do-search")
            self._finish_step(ctx.run, click, final_url=ctx.page.url)

        async def read_results(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "results")
            entry = self._step(ctx.run, StepKind.EXTRACT, "Read the result counter and rows",
                               label_anchor="#result-counter")
            counter = (await ctx.page.inner_text("#result-counter")).strip()
            skus = await ctx.page.eval_on_selector_all(
                "li.result", "els => els.map(e => e.dataset.sku)")
            ctx.candidate = {"counter_text": counter, "skus": skus, "term": term}
            self._finish_step(ctx.run, entry, counter_text=counter, skus=skus)

        return Plan("GS-1", f"Fixture catalogue search for '{term or "(no term named)"}' "
                            f"(POST-only form)",
                    ("fill search field", "submit form by POST"),
                    (open_form, fill_and_submit, read_results))

    def _plan_paginate(self, low: str) -> Plan:
        m = re.search(r"page\s*(\d+)", low)
        target = int(m.group(1)) if m else 2

        async def open_browse(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, f"{settings.fixture_base_url}/browse")

        async def advance(ctx: ExecutionContext) -> None:
            url_before = ctx.page.url
            for n in range(target - 1):
                if ctx.deadline_exceeded():
                    return
                entry = self._step(
                    ctx.run, StepKind.CLICK, f"Click 'Next' ({n + 1} of {target - 1})",
                    selector="#next",
                    why="GS-2: pagination is client-side and the URL never changes, so "
                        "page N cannot be reached by navigating to it.")
                await ctx.page.click("#next")
                await ctx.page.wait_for_timeout(120)
                self._finish_step(ctx.run, entry,
                                  page_after=await ctx.page.inner_text("#page-num"))
            after = ctx.page.url
            state = self._step(ctx.run, StepKind.NOTE, "URL unchanged across pagination",
                               url_before=url_before, url_after=after,
                               url_changed=url_before != after)
            self._finish_step(ctx.run, state, ok=url_before == after)

        async def read_page(ctx: ExecutionContext) -> None:
            await self._capture(ctx, f"page-{target}")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               f"Read the visible rows on page {target}",
                               label_anchor="#page-position")
            position = (await ctx.page.inner_text("#page-position")).strip()
            skus = await ctx.page.eval_on_selector_all(
                "#pages .page:not([hidden]) li.result", "els => els.map(e => e.dataset.sku)")
            ctx.candidate = {"pager_text": position, "skus": skus, "page": target}
            self._finish_step(ctx.run, entry, pager_text=position, skus=skus)

        return Plan("GS-2", f"Fixture pagination to page {target} (no URL change)",
                    (f"click Next {target - 1}x",),
                    (open_browse, advance, read_page))

    def _plan_overlay(self) -> Plan:
        async def open_gated(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, f"{settings.fixture_base_url}/gated")

        async def probe_blocked(ctx: ExecutionContext) -> None:
            """Show the overlay genuinely blocks, rather than asserting that it does."""
            entry = self._step(ctx.run, StepKind.NOTE,
                               "Confirm the underlying control is not actionable yet",
                               selector="#reveal")
            disabled = await ctx.page.is_disabled("#reveal")
            self._finish_step(ctx.run, entry, reveal_disabled=disabled,
                              diagnosed=DiagnosedCause.OBSCURED_BY_OVERLAY.value)
            entry.diagnosed_cause = DiagnosedCause.OBSCURED_BY_OVERLAY
            self._store.save_trace_entry(ctx.run.id, entry)

        async def dismiss_and_act(ctx: ExecutionContext) -> None:
            click = self._step(ctx.run, StepKind.CLICK, "Dismiss the blocking overlay",
                               selector="#dismiss",
                               why="GS-3: the control beneath is disabled until the "
                                   "overlay is dismissed.")
            await ctx.page.click("#dismiss")
            await ctx.page.wait_for_selector("#overlay", state="detached", timeout=5_000)
            self._finish_step(ctx.run, click,
                              reveal_disabled_after=await ctx.page.is_disabled("#reveal"))
            act = self._step(ctx.run, StepKind.CLICK, "Perform the underlying action",
                             selector="#reveal")
            await ctx.page.click("#reveal")
            await ctx.page.wait_for_selector("#code", state="visible", timeout=5_000)
            self._finish_step(ctx.run, act)

        async def read_code(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "revealed")
            entry = self._step(ctx.run, StepKind.EXTRACT, "Read the revealed product code",
                               label_anchor="th:text('Product code')")
            code = (await ctx.page.inner_text("#code")).strip()
            ctx.candidate = {"product_code": code}
            self._finish_step(ctx.run, entry, product_code=code)

        return Plan("GS-3", "Fixture overlay dismissal, then the underlying action",
                    ("dismiss overlay", "click reveal"),
                    (open_gated, probe_blocked, dismiss_and_act, read_code))

    def _plan_notes(self) -> Plan:
        async def open_notes(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, f"{settings.fixture_base_url}/notes")

        async def read_notes(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "notes")
            entry = self._step(
                ctx.run, StepKind.NOTE,
                "Page content read as data; goal and policy are not model-mutable",
                note="M1 has no model in the loop, so there is no objective for page text "
                     "to redirect. The structural defence (fixed action allow-list, goal "
                     "and postcondition outside model-mutable state, navigation origin "
                     "policy) is what makes this safe once the planner exists at M3; "
                     "injection detection itself is an M6 deliverable.")
            self._finish_step(ctx.run, entry)
            ctx.candidate = {"note_count": await ctx.page.eval_on_selector_all(
                "table tr", "els => els.length")}

        return Plan("GS-injection", "Fixture injection page (read-only in M1)",
                    ("navigate to the injection page",), (open_notes, read_notes))

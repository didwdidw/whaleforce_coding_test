"""M2 executor — deterministic, with no model in the loop at all.

The shape is unchanged from M1: scripted plans against the fixture, exercising the browser
lifecycle, egress enforcement, artifact capture, budgets and the status taxonomy. What
changed is what decides the outcome. Every plan now freezes a postcondition **before it
browses**, and the terminal status comes from `app.verifier` re-extracting the answer from
the stored artifact — not from the executor's own reading of the live page.

That ordering is the point. The executor is allowed to be wrong; it has been. What it is not
allowed to do is grade itself.

Task routing here is keyword matching, not understanding. Anything it does not recognise
abstains with a reason naming what was missing (A2.2) rather than guessing, and anything
that matches more than one operation abstains too.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page

from app import egress
from app.browser import BrowserSupervisor, BrowserUnavailable
from app.config import settings
from app.coverage import CoverageLedger
from app.models import (
    DiagnosedCause, FailureClass, Run, RunState, StepKind, TerminalStatus, Tier, TraceEntry,
)
from app.postcondition import (
    AbsenceMode, ClaimSpec, Postcondition, Relation, RequiredAction,
)
from app.robots import RobotsCache
from app.store import Store
from app.verifier import Verifier

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

#: Asking for the answer instead of finding it. The hook is also robots-Disallowed, so the
#: refusal cites a rule rather than a preference.
TESTHOOK_PATH = "/__testhook__/ground-truth"

SHORTCUT = re.compile(r"without (clicking|paginating|interacting|using the pager)"
                      r"|straight from the dom|shortcut")

RESULT_ROWS = '//ul[contains(@class,"results")]//li[contains(@class,"result")]'
VISIBLE_PAGE_ROWS = ('//div[@id="pages"]/div[contains(@class,"page") and not(@hidden)]'
                     '//li[contains(@class,"result")]')
ALL_PAGE_ROWS = '//div[@id="pages"]//li[contains(@class,"result")]'
OVERLAY_ANCHOR = '//*[contains(normalize-space(.), "Before you continue")][not(.//*[contains(normalize-space(.), "Before you continue")])]'


@dataclass
class Plan:
    """A scripted sequence plus the postcondition it commits to. At M3 the planner produces
    these from the model's candidates; the postcondition stays code-owned."""

    operation: str
    label: str
    postcondition: Postcondition
    steps: tuple[Callable[["ExecutionContext"], Awaitable[None]], ...]


@dataclass
class ExecutionContext:
    run: Run
    page: Page
    context: BrowserContext
    store: Store
    candidate: dict[str, Any] = field(default_factory=dict)
    #: The snapshot the claims were read from — verification re-resolves anchors in this.
    evidence_artifact: str | None = None

    def deadline_exceeded(self) -> bool:
        return self.run.budget.elapsed_seconds > settings.budgets.wall_clock_seconds


class Executor:
    def __init__(self, supervisor: BrowserSupervisor, store: Store,
                 robots: RobotsCache | None = None) -> None:
        self._supervisor = supervisor
        self._store = store
        self._robots = robots or RobotsCache()
        self._verifier = Verifier(store)
        self._coverage = CoverageLedger(store)

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
        self._coverage.record(status=status, failure=failure, run_id=run.id, task=run.task)

    # ---- entry point -----------------------------------------------------------

    async def execute(self, run: Run) -> None:
        run.state = RunState.RUNNING
        run.started_at = run.started_at or time.time()
        run.budget.started_at = run.started_at
        # M2 has no model in the loop, so no credential is used at all. Recording it
        # keeps A8.9's disclosure accurate rather than blank.
        run.credential_tier = "none (no model call in M2)"
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
                 "This build runs scripted operations against the fixture with no model in "
                 "the loop, so it cannot plan for an arbitrary task. It stopped before "
                 "browsing rather than guessing. Recognised inputs are listed on the "
                 "submit form."))
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
            ctx = ExecutionContext(run=run, page=page, context=context, store=self._store)

            self._freeze(run, plan)

            for step in plan.steps:
                if run.budget.steps >= settings.budgets.max_steps:
                    self._terminate(
                        run, TerminalStatus.FAILED, FailureClass.BUDGET_EXHAUSTED,
                        f"The run reached its {settings.budgets.max_steps}-step budget.")
                    return
                await step(ctx)
                if run.terminal_status is not None:
                    return

            await self._verify(run, ctx)

    def _freeze(self, run: Run, plan: Plan) -> None:
        """Serialise and hash the postcondition before anything is browsed (S-4.12)."""
        run.postcondition = plan.postcondition.to_dict()
        run.postcondition_hash = plan.postcondition.sha256
        self._store.save_run(run)
        entry = self._step(run, StepKind.NOTE, f"Postcondition frozen: {plan.label}",
                           operation=plan.operation,
                           postcondition_hash=run.postcondition_hash,
                           postcondition=run.postcondition,
                           browser_generation=run.browser_generation,
                           note="Frozen before execution. Verification re-checks against "
                                "this object, so recovery cannot lower the bar.")
        self._finish_step(run, entry)

    async def _verify(self, run: Run, ctx: ExecutionContext) -> None:
        """Hand the run to the verifier and adopt its verdict. The executor has no way to
        set a success status itself (S-4.7)."""
        entry = self._step(run, StepKind.EXTRACT, "Deterministic verification",
                           artifact_id=ctx.evidence_artifact,
                           note="Re-resolves the frozen anchors inside the full stored "
                                "artifact and re-extracts each value independently of the "
                                "reading taken during execution (S-4.8, A7.4).")
        verdict = self._verifier.verify(run, artifact_id=ctx.evidence_artifact,
                                        candidate=ctx.candidate)
        self._finish_step(run, entry, ok=verdict.counts_as_success,
                          verdict=verdict.to_dict())

        run.claims = [c.to_dict() for c in verdict.claims]
        self._store.save_run(run)
        self._terminate(run, verdict.status, verdict.failure_class, verdict.explanation)

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
        ctx.evidence_artifact = ref.id
        return ref.id

    # ---- routing ---------------------------------------------------------------

    # Every marker is distinctive to one operation. A bare "page" is not a marker: "the
    # gated page" would otherwise route an overlay task to the paginator, which then returns
    # a perfectly plausible pager reading for a task that asked for something else. A
    # mis-route that still produces an answer is worse than one that fails.
    ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("testhook", ("ground truth", "test hook", "testhook", "answer key")),
        ("notes", ("injection", "customer note", "notes page")),
        ("overlay", ("overlay", "dismiss", "modal", "gated", "reference code")),
        ("absence", ("priced over", "priced above", "costs more than", "over £",
                     "above £", "more expensive than")),
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
        seed = self._seed(low)
        if name == "testhook":
            return self._plan_testhook(seed)
        if name == "notes":
            return self._plan_notes(seed)
        if name == "overlay":
            return self._plan_overlay(seed)
        if name == "absence":
            return self._plan_absence(low, seed)
        if name == "paginate":
            # A shortcut is a variant of the same operation, not a second one — routing it
            # separately would make every shortcut task ambiguous and abstain, which would
            # hide exactly the case S-4.4 requires us to score.
            return (self._plan_paginate_shortcut(low, seed) if SHORTCUT.search(low)
                    else self._plan_paginate(low, seed))
        return self._plan_search(low, seed)

    @staticmethod
    def _seed(low: str) -> str:
        """Mutation seed, recorded with every run so a result is reproducible (S-9.4)."""
        m = re.search(r"\bseed[: ]+([a-z0-9-]+)", low)
        return m.group(1) if m else "none"

    def _url(self, path: str, seed: str) -> str:
        base = f"{settings.fixture_base_url}{path}"
        return f"{base}?seed={seed}" if seed and seed != "none" else base

    @staticmethod
    def _search_term(low: str) -> str | None:
        """The term to search for, or None if the task does not name one.

        A greedy character class swallows the whole sentence: "search the fixture catalogue
        for lantern" yielded "the fixture catalogue for lant", which returns zero results
        and reads like a real answer. Quoted text wins; otherwise the words after the last
        "for"; and a term is never invented.
        """
        low = re.sub(r"\bseed[: ]+[a-z0-9-]+", "", low).strip()
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

    # ---- plans -----------------------------------------------------------------

    def _plan_search(self, low: str, seed: str) -> Plan:
        term = self._search_term(low)
        pc = Postcondition(
            goal=f"Return the catalogue search result set for {term!r}",
            operation="GS-1",
            target_url=self._url("/search", seed).split("?")[0],
            inputs={"term": term, "seed": seed},
            required_actions=(
                RequiredAction("fill", "#q", "the term must be typed into the form"),
                RequiredAction("click", "#do-search",
                               "results exist only behind a POST; no URL expresses them"),
            ),
            claims=(
                ClaimSpec("result_counter", 'N results for "term"', Relation.COUNTER_ECHO,
                          "counter"),
                # Required: a verified count with unverifiable contents is not an answer to
                # "what matched". When the set is empty the absence branch decides first,
                # so an unresolvable row container does not punish a legitimate empty page.
                ClaimSpec("items", "result rows", Relation.LIST_ENUMERATION, "sku_list",
                          container=RESULT_ROWS),
                ClaimSpec("empty_state", "No products match that search",
                          Relation.EMPTY_STATE, "bool", optional=True),
            ),
            absence=AbsenceMode.A_EMPTY_STATE,
        )

        async def open_form(ctx: ExecutionContext) -> None:
            if term is None:
                self._terminate(
                    ctx.run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                    "The task asks for a search but does not name a term to search for. "
                    "Guessing one would produce a result set nobody asked about, so the "
                    "run stopped before browsing.")
                return
            await self._navigate(ctx, self._url("/", seed))

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
            empty = await ctx.page.query_selector("#no-results")
            m = re.search(r"(\d+)\s+results?\s+for\s+[\"“](.*?)[\"”]", counter, re.S)
            ctx.candidate = {
                "result_counter": {"count": int(m.group(1)) if m else None,
                                   "term": m.group(2) if m else None},
                "items": skus,
                "empty_state": bool(empty),
            }
            self._finish_step(ctx.run, entry, counter_text=counter, skus=skus,
                              empty_state=bool(empty))

        return Plan("GS-1", f"Fixture catalogue search for '{term or '(no term named)'}' "
                            f"(POST-only form)",
                    pc, (open_form, fill_and_submit, read_results))

    def _paginate_postcondition(self, target: int, seed: str, *,
                                required: tuple[RequiredAction, ...]) -> Postcondition:
        return Postcondition(
            goal=f"Report the catalogue rows visible on result page {target}",
            operation="GS-2",
            target_url=self._url("/browse", seed).split("?")[0],
            inputs={"page": target, "seed": seed},
            required_actions=required,
            claims=(
                ClaimSpec("pager", "Page N of M", Relation.PAGER_POSITION, "pager"),
                ClaimSpec("items", "rows on the visible page", Relation.LIST_ENUMERATION,
                          "sku_list", container=VISIBLE_PAGE_ROWS),
            ),
        )

    def _plan_paginate(self, low: str, seed: str) -> Plan:
        m = re.search(r"page\s*(\d+)", low)
        target = int(m.group(1)) if m else 2
        pc = self._paginate_postcondition(
            target, seed,
            required=(RequiredAction("click", "#next",
                                     "pagination is client-side; page N has no address",
                                     times=max(1, target - 1)),))

        async def open_browse(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, self._url("/browse", seed))

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

        return Plan("GS-2", f"Fixture pagination to page {target} (no URL change)",
                    pc, (open_browse, advance, self._read_visible_page(target)))

    def _plan_paginate_shortcut(self, low: str, seed: str) -> Plan:
        """The deliberate shortcut case S-4.4 requires.

        Every page's rows are in the DOM from the first load, so page 2 can be read without
        touching the pager. The values it produces are *correct*. The postcondition still
        declares the click, so the verifier scores it `failed / required_action_skipped` —
        the capability being claimed is the interaction, not the number.
        """
        m = re.search(r"page\s*(\d+)", low)
        target = int(m.group(1)) if m else 2
        pc = self._paginate_postcondition(
            target, seed,
            required=(RequiredAction("click", "#next",
                                     "pagination is client-side; page N has no address",
                                     times=max(1, target - 1)),))

        async def open_browse(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, self._url("/browse", seed))

        async def read_hidden(ctx: ExecutionContext) -> None:
            note = self._step(
                ctx.run, StepKind.NOTE,
                f"Reading page {target} out of the DOM without using the pager",
                note="Deliberate shortcut (S-4.4). The value will be right and the run is "
                     "still scored a failure, because the declared required action did not "
                     "happen.")
            self._finish_step(ctx.run, note)
            await ctx.page.eval_on_selector_all(
                "#pages .page", f"els => els.forEach(e => e.hidden = "
                                f"Number(e.dataset.page) !== {target})")
            await self._capture(ctx, f"page-{target}-shortcut")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               f"Read page {target} rows directly", label_anchor="#pages")
            skus = await ctx.page.eval_on_selector_all(
                f'#pages .page[data-page="{target}"] li.result',
                "els => els.map(e => e.dataset.sku)")
            position = (await ctx.page.inner_text("#page-position")).strip()
            pm = re.search(r"page\s+(\d+)\s+of\s+(\d+).*?(\d+)\s+products", position,
                           re.I | re.S)
            ctx.candidate = {
                "items": skus,
                "pager": {"page": target,
                          "total": int(pm.group(2)) if pm else None,
                          "items": int(pm.group(3)) if pm else None},
            }
            self._finish_step(ctx.run, entry, skus=skus, pager_text=position)

        return Plan("GS-2-shortcut",
                    f"Fixture page {target} read without paginating (shortcut case)",
                    pc, (open_browse, read_hidden))

    def _read_visible_page(self, target: int) -> Callable[[ExecutionContext], Awaitable[None]]:
        async def read_page(ctx: ExecutionContext) -> None:
            await self._capture(ctx, f"page-{target}")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               f"Read the visible rows on page {target}",
                               label_anchor="#page-position")
            position = (await ctx.page.inner_text("#page-position")).strip()
            skus = await ctx.page.eval_on_selector_all(
                "#pages .page:not([hidden]) li.result", "els => els.map(e => e.dataset.sku)")
            pm = re.search(r"page\s+(\d+)\s+of\s+(\d+).*?(\d+)\s+products", position,
                           re.I | re.S)
            ctx.candidate = {
                "pager": {"page": int(pm.group(1)) if pm else None,
                          "total": int(pm.group(2)) if pm else None,
                          "items": int(pm.group(3)) if pm else None},
                "items": skus,
            }
            self._finish_step(ctx.run, entry, pager_text=position, skus=skus)

        return read_page

    def _plan_absence(self, low: str, seed: str) -> Plan:
        """Absence proven by enumeration (Amendment 3, Mode B).

        The threshold is read from the task and frozen. If the task names no threshold the
        plan abstains rather than picking one — a predicate nobody asked for would produce
        a perfectly verifiable answer to the wrong question.
        """
        m = re.search(r"(?:over|above|more than|more expensive than)\s*£?\s*"
                      r"([0-9]+(?:\.[0-9]+)?)", low)
        threshold = float(m.group(1)) if m else None
        pc = Postcondition(
            goal=f"Determine whether any catalogue item is priced over £{threshold}",
            operation="GS-4",
            target_url=self._url("/browse", seed).split("?")[0],
            inputs={"seed": seed,
                    "predicate": {"field": "price_gbp", "op": ">", "value": threshold}},
            required_actions=(
                RequiredAction("click", "#next",
                               "every page must be visited before absence is claimed"),
            ),
            claims=(
                ClaimSpec("coverage", "Page N of M · K products", Relation.PAGER_POSITION,
                          "pager"),
                ClaimSpec("items", "every catalogue row in the artifact",
                          Relation.LIST_ENUMERATION, "sku_list", container=ALL_PAGE_ROWS),
            ),
            absence=AbsenceMode.B_ENUMERATION,
            coverage_anchor="the browse pager's own product total",
        )

        async def open_browse(ctx: ExecutionContext) -> None:
            if threshold is None:
                self._terminate(
                    ctx.run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                    "The task asks whether anything is priced above a threshold but does "
                    "not name one. Choosing a threshold would answer a different question, "
                    "so the run stopped before browsing.")
                return
            await self._navigate(ctx, self._url("/browse", seed))

        async def visit_every_page(ctx: ExecutionContext) -> None:
            total = int((await ctx.page.inner_text("#page-total")).strip())
            for n in range(total - 1):
                if ctx.deadline_exceeded():
                    return
                entry = self._step(
                    ctx.run, StepKind.CLICK, f"Click 'Next' to page {n + 2} of {total}",
                    selector="#next",
                    why="Absence by enumeration requires every page to be visited, not "
                        "only counted.")
                await ctx.page.click("#next")
                await ctx.page.wait_for_timeout(120)
                self._finish_step(ctx.run, entry)

        async def enumerate_all(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "enumeration")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               "Enumerate every row and compare against the pager's total",
                               label_anchor="#page-position")
            position = (await ctx.page.inner_text("#page-position")).strip()
            rows = await ctx.page.eval_on_selector_all(
                "#pages li.result",
                "els => els.map(e => ({sku: e.dataset.sku, text: e.innerText}))")
            pm = re.search(r"page\s+(\d+)\s+of\s+(\d+).*?(\d+)\s+products", position,
                           re.I | re.S)
            matches = [r["sku"] for r in rows
                       if (p := re.search(r"£\s*([0-9.]+)", r["text"] or ""))
                       and float(p.group(1)) > threshold]
            ctx.candidate = {
                "coverage": {"page": int(pm.group(1)) if pm else None,
                             "total": int(pm.group(2)) if pm else None,
                             "items": int(pm.group(3)) if pm else None},
                "items": [r["sku"] for r in rows],
                "matches": matches,
            }
            self._finish_step(ctx.run, entry, enumerated=len(rows), pager_text=position,
                              matches=matches)

        return Plan("GS-4", f"Is any catalogue item priced over £{threshold}? "
                            f"(absence by enumeration)",
                    pc, (open_browse, visit_every_page, enumerate_all))

    def _plan_overlay(self, seed: str) -> Plan:
        pc = Postcondition(
            goal="Read the reference code that is only reachable after dismissing the overlay",
            operation="GS-3",
            target_url=self._url("/gated", seed).split("?")[0],
            inputs={"seed": seed},
            required_actions=(
                RequiredAction("click", "#dismiss", "the control beneath is disabled until "
                                                    "the overlay is dismissed"),
                RequiredAction("click", "#reveal", "the code is not in the DOM until the "
                                                   "underlying action is taken"),
            ),
            claims=(
                ClaimSpec("product_code", "Product code", Relation.TABLE_ROW_CELL, "code"),
                ClaimSpec("stock_on_hand", "Stock on hand", Relation.TABLE_ROW_CELL,
                          "integer"),
                ClaimSpec("overlay_gone", "the blocking overlay", Relation.ELEMENT_ABSENT,
                          "bool", container=OVERLAY_ANCHOR),
            ),
        )

        async def open_gated(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, self._url("/gated", seed))

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
                               label_anchor="Product code")
            code = (await ctx.page.inner_text("#code")).strip()
            stock = (await ctx.page.inner_text(
                "//th[normalize-space()='Stock on hand']/following-sibling::td[1]")).strip()
            ctx.candidate = {"product_code": code, "stock_on_hand": stock,
                             "overlay_gone": True}
            self._finish_step(ctx.run, entry, product_code=code, stock_on_hand=stock)

        return Plan("GS-3", "Fixture overlay dismissal, then the underlying action",
                    pc, (open_gated, probe_blocked, dismiss_and_act, read_code))

    def _plan_notes(self, seed: str) -> Plan:
        pc = Postcondition(
            goal="Read the customer notes page as data",
            operation="GS-injection",
            target_url=self._url("/notes", seed).split("?")[0],
            inputs={"seed": seed},
            required_actions=(),
            claims=(ClaimSpec("first_note", "Note 4471", Relation.TABLE_ROW_CELL, "text"),),
        )

        async def open_notes(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, self._url("/notes", seed))

        async def read_notes(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "notes")
            entry = self._step(
                ctx.run, StepKind.NOTE,
                "Page content read as data; goal and policy are not model-mutable",
                note="M2 has no model in the loop, so there is no objective for page text "
                     "to redirect. The structural defence (fixed action allow-list, goal "
                     "and postcondition outside model-mutable state, navigation origin "
                     "policy) is what makes this safe once the planner exists at M3; "
                     "injection detection itself is an M6 deliverable.")
            self._finish_step(ctx.run, entry)
            first = (await ctx.page.inner_text(
                "//th[normalize-space()='Note 4471']/following-sibling::td[1]")).strip()
            ctx.candidate = {"first_note": first}

        return Plan("GS-injection", "Fixture injection page (read-only until M6)",
                    pc, (open_notes, read_notes))

    def _plan_testhook(self, seed: str) -> Plan:
        """Asking for the answer key. The fixture Disallows the hook in robots.txt, so this
        is refused by a rule that can be quoted rather than by our own preference."""
        pc = Postcondition(
            goal="Read the fixture's ground-truth hook",
            operation="GS-cheat",
            target_url=self._url(TESTHOOK_PATH, seed).split("?")[0],
            inputs={"seed": seed},
            claims=(),
        )

        async def attempt(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, self._url(TESTHOOK_PATH, seed))

        return Plan("GS-cheat", "Ground-truth hook (robots-Disallowed by construction)",
                    pc, (attempt,))

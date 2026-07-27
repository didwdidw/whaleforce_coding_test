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
from app.identity import COLLECT_JS, ElementIdentity, identify
from app.models import (
    DiagnosedCause, FailureClass, Run, RunState, StepKind, TerminalStatus, Tier, TraceEntry,
)
from app.models import StrategyFamily
from app.planner import Planner, Proposal, ProposalRejected
from app.postcondition import (
    AbsenceMode, ClaimSpec, Postcondition, Relation, RequiredAction,
)
from app.provider import Provider, ProviderError, RunBudget
from app.reduce import reduce_page, reduction_record
from app.robots import RobotsCache
from app.store import Store
from app.suspicion import annotate
from app.verifier import Verifier

log = logging.getLogger(__name__)


def norm_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()

#: Which trace step kind each proposed action is recorded as.
_STEP_KINDS = {
    "click": StepKind.CLICK, "fill": StepKind.FILL, "select": StepKind.SELECT,
    "press": StepKind.PRESS, "wait_for": StepKind.WAIT_FOR, "extract": StepKind.EXTRACT,
}

@dataclass(frozen=True)
class PromisedRecord:
    """A promised `site × operation` record (S-1.3), keyed by the route that serves it.

    This is the single list. Admission reads it to decide `T-DECLARED`, and the support
    page renders it, so the page cannot claim a record the router cannot reach — which is
    how the page came to advertise four unimplemented operations after they shipped.
    """

    id: str
    site: str
    operation: str
    route: str


PROMISED_RECORDS: tuple[PromisedRecord, ...] = (
    PromisedRecord("OP-4", "en.wikipedia.org",
                   "Sort a sortable table by a named column, read a cell from the top row",
                   "wiki_sort"),
    PromisedRecord("OP-5", "en.wikipedia.org",
                   "Expand a collapsed box and extract a value not visible beforehand",
                   "wiki_expand"),
    PromisedRecord("OP-6", "books.toscrape.com",
                   "Category navigation and pagination, list-level facts", "book_category"),
    PromisedRecord("OP-7", "books.toscrape.com",
                   "Open a product page and extract a labelled field", "book_detail"),
)

RECORD_BY_ROUTE: dict[str, PromisedRecord] = {r.route: r for r in PROMISED_RECORDS}

#: A task asks for the planner explicitly, or configuration forces it. The deterministic
#: path stays the default: it needs no quota, and it is what the fixture demonstrations run
#: on so that a visitor never depends on a provider being reachable.
PLANNER_MARKER = re.compile(r"\b(use the planner|with the planner|planner mode)\b")

#: The other direction: ask for the deterministic script explicitly. It is the comparison
#: baseline for the analysis report, so it needs to be requestable on a real site without
#: turning the provider off.
SCRIPT_MARKER = re.compile(r"\b(without the planner|scripted path|scripted mode|"
                           r"deterministic path)\b")

# Phrases that put a task outside scope before any browsing happens (S-2.1).
#
# These match the *act being asked for*, not words that happen to appear. The first version
# matched nouns, and the result was a refusal that looked exactly like caution: a bare
# `order` refused "sort in descending order", and `book a` refused "read the product page
# for the book A Light in the Attic" — our own OP-7 case, phrased the way a person would.
# A refusal is the safe-looking answer, so nothing complained, and the corpus below is what
# makes the difference between this control working and this control being always-on
# visible at all. Both halves of it are load-bearing: what must be refused, and what must
# not.
OUT_OF_SCOPE = (
    (r"\b(log ?in|logging in|sign ?in|sign up|create an account|my account|"
     r"password|credentials?)\b", "authentication or a login flow"),
    (r"\b(brokerage|bank account|my portfolio|"
     r"(my|your|their) account balance|"
     r"my (orders?|cart|basket|email|inbox|account))\b", "private or personal data"),
    (r"\b(buy|purchase|place an order|order (me|us) |check ?out|pay for|"
     r"add (it )?to (the )?(cart|basket)|"
     r"book (a|an|me) (table|room|flight|seat|ticket|appointment|slot)|"
     r"reserve (a|an|me) (table|room|seat|ticket|slot|copy)|subscribe to)\b",
     "a transaction or a state change"),
    (r"\b(post a|submit an? (review|comment|form|rating)|leave an? (review|comment)|"
     r"delete|update my|send an? (email|message))\b", "writing to a third party"),
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
BOOKS = "https://books.toscrape.com"
BOOK_CATEGORY_POETRY = f"{BOOKS}/catalogue/category/books/poetry_23/index.html"
BOOK_DETAIL_URL = f"{BOOKS}/catalogue/a-light-in-the-attic_1000/index.html"
BOOK_CATEGORY_NONFICTION = f"{BOOKS}/catalogue/category/books/nonfiction_13/index.html"
BOOK_CATEGORY_NONFICTION_P2 = f"{BOOKS}/catalogue/category/books/nonfiction_13/page-2.html"
WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CONSTITUENTS = '//table[@id="constituents"]'
WIKI_SPECIAL = "https://en.wikipedia.org/wiki/Special:WhatLinksHere/"
NAVBOX_TOGGLE = ".navbox-inner.mw-collapsible .mw-collapsible-toggle"
COLLAPSED_NAVBOX = ('//div[contains(@class,"navbox-inner") '
                    'and contains(@class,"mw-collapsed")]')

OVERLAY_ANCHOR = '//*[contains(normalize-space(.), "Before you continue")][not(.//*[contains(normalize-space(.), "Before you continue")])]'


@dataclass
class Plan:
    """A postcondition plus two ways of satisfying it.

    `steps` is the deterministic script. `entry_url`, `goal` and `terms` are what the
    model-driven loop needs instead: where to start, what it is trying to achieve, and the
    words the snapshot reducer should keep the page around.

    The postcondition is the same object either way, and it is code-owned in both. That is
    what makes the two paths comparable: same bar, different way of reaching it.
    """

    operation: str
    label: str
    postcondition: Postcondition
    steps: tuple[Callable[["ExecutionContext"], Awaitable[None]], ...]
    entry_url: str = ""
    terms: tuple[str, ...] = ()
    #: The final read, reused by the planned path once the model says it is finished. The
    #: model drives the interaction; the candidate it will be judged on is still produced
    #: by deterministic code, so a model cannot both act and report.
    read_step: Callable[["ExecutionContext"], Awaitable[None]] | None = None


@dataclass
class ExecutionContext:
    run: Run
    page: Page
    context: BrowserContext
    store: Store
    candidate: dict[str, Any] = field(default_factory=dict)
    #: The snapshot the claims were read from — verification re-resolves anchors in this.
    evidence_artifact: str | None = None
    #: What the last action actually produced, fed back so the planner can tell a step that
    #: worked from one that did nothing.
    last_observed: str = ""

    def deadline_exceeded(self) -> bool:
        return self.run.budget.elapsed_seconds > settings.budgets.wall_clock_seconds


class Executor:
    def __init__(self, supervisor: BrowserSupervisor, store: Store,
                 robots: RobotsCache | None = None,
                 provider: Provider | None = None) -> None:
        self._supervisor = supervisor
        self._store = store
        self._robots = robots or RobotsCache()
        self._verifier = Verifier(store)
        self._coverage = CoverageLedger(store)
        self._provider = provider or Provider(ledger=store)
        self._planner = Planner(self._provider)

    # ---- admission-time classification -----------------------------------------

    def classify(self, task: str) -> tuple[Tier, str | None]:
        """Tier is decided before execution starts (S-1.3).

        The second element is why: the refused act, or the promised record the task maps
        to. Routing to exactly one promised record is what T-DECLARED means, so the two
        cannot disagree — before this, no run could ever be labelled T-DECLARED and every
        promised-record run was reported as best-effort.
        """
        low = task.lower()
        for pattern, what in OUT_OF_SCOPE:
            if re.search(pattern, low):
                return Tier.REFUSED, what
        operation, _, _ = self.route(task)
        record = RECORD_BY_ROUTE.get(operation or "")
        if record is not None:
            return Tier.DECLARED, record.id
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
        # Every run ends here, so this is where a quiet outcome is made to answer for what
        # the trace says we may have removed before anyone could act on it.
        annotate(run)
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
                 "This task does not map to any operation this build can plan for, so it "
                 "stopped before browsing rather than guessing. This is a gap in the "
                 "build, not a policy decision about the task: attempting an arbitrary "
                 "read-only site through the generic loop is not in this milestone. "
                 "Recognised inputs are listed on the submit form."))
            return

        low = run.task.lower()
        asked_for_planner = bool(PLANNER_MARKER.search(low)) or settings.planner_forced
        asked_for_script = bool(SCRIPT_MARKER.search(low))
        if asked_for_planner and not plan.entry_url:
            self._terminate(
                run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                f"The planner was requested but the {plan.operation} operation has no "
                f"model-driven form: it is a policy demonstration, not a browsing task.")
            return
        if asked_for_planner and not self._provider.configured():
            # Named degradation rather than an obscure failure: the deterministic path is
            # unaffected and says so.
            self._terminate(
                run, TerminalStatus.BLOCKED, FailureClass.PROVIDER_ERROR,
                "No provider credential is readable, so the planner cannot run. Every "
                "deterministic operation still works — submit the same task without asking "
                "for the planner and it will execute and be verified.")
            return

        planned, why = self._choose_path(plan, asked_for_planner, asked_for_script)
        run.execution_path = "model_driven" if planned else "scripted"
        self._store.save_run(run)
        entry = self._step(run, StepKind.NOTE,
                           f"Execution path: {run.execution_path} ({why})",
                           execution_path=run.execution_path, reason=why)
        self._finish_step(run, entry)

        runner = self._run_planned(run, plan) if planned else self._run_plan(run, plan)
        try:
            await asyncio.wait_for(runner,
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

    def _choose_path(self, plan: Plan, asked_for_planner: bool,
                     asked_for_script: bool) -> tuple[bool, str]:
        """Which of the two paths runs, and why in words the trace can carry (A13.4).

        Model-driven is the default for real-site operations. The deterministic script
        keeps three jobs: the fixture demonstrations, which must not depend on a provider;
        the fallback when no credential is readable; and the baseline the report compares
        against.
        """
        if asked_for_planner:
            return True, "requested"
        if asked_for_script:
            return False, "deterministic path requested as the comparison baseline"
        if not plan.entry_url:
            return False, "policy demonstration, not a browsing task"
        if not settings.planner_default_on_real_sites:
            return False, "model-driven default disabled by configuration"
        if urlsplit(plan.entry_url).netloc == urlsplit(settings.fixture_base_url).netloc:
            return False, "fixture demonstration, which must not depend on a provider"
        if not self._provider.configured():
            return False, "no provider credential readable, falling back to the script"
        return True, "default for a promised record on a real site"

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


    # ---- the model-driven loop -------------------------------------------------

    async def _run_planned(self, run: Run, plan: Plan) -> None:
        """The same postcondition, reached by a model proposing one action at a time.

        The division of labour is the point. The model sees a reduced view and proposes an
        action; code decides whether that action is allowed, executes it, diagnoses what
        went wrong, and produces the candidate that will be judged. The model never sets a
        status and never writes the postcondition.
        """
        async with self._supervisor.context() as (context, generation):
            run.browser_generation = generation
            self._store.save_run(run)
            page = await context.new_page()
            await self._guard_page(run, page)
            ctx = ExecutionContext(run=run, page=page, context=context, store=self._store)
            self._freeze(run, plan)

            if not await self._navigate(ctx, plan.entry_url):
                return

            budget = RunBudget()
            history: list[str] = []
            already_read = False
            recovery: dict[str, Any] | None = None
            families_tried: list[str] = []
            step = 0

            while True:
                step += 1
                if run.budget.steps >= settings.budgets.max_steps:
                    self._terminate(
                        run, TerminalStatus.FAILED, FailureClass.BUDGET_EXHAUSTED,
                        f"The run reached its {settings.budgets.max_steps}-step budget "
                        f"without reaching the frozen postcondition. Budgets are "
                        f"fail-closed: no partial answer is emitted in their place.")
                    return
                if ctx.deadline_exceeded():
                    self._terminate(run, TerminalStatus.FAILED, FailureClass.TIMEOUT,
                                    "The run exceeded its wall-clock budget.")
                    return

                artifact_id = await self._capture(ctx, f"step-{step}")
                view = await reduce_page(page, plan.terms)
                purpose = "recovery" if recovery else "exploration"

                prompt = self._planner.build_prompt(
                    plan.postcondition.goal, view, step=step, history=history,
                    recovery=recovery)
                call = self._step(
                    run, StepKind.NOTE,
                    f"Model call ({purpose}) for step {step}",
                    purpose=purpose,
                    reduction=reduction_record(view, artifact_id),
                    prompt_chars=len(prompt))
                try:
                    proposal = self._planner.propose(prompt, budget=budget,
                                                     purpose=purpose, view=view)
                except ProposalRejected as exc:
                    # Outside the contract. Recorded and refused, never repaired into
                    # something plausible.
                    self._finish_step(run, call, ok=False, rejected=exc.reason,
                                      response_head=exc.raw)
                    self._terminate(
                        run, TerminalStatus.FAILED, FailureClass.INTERNAL_ERROR,
                        f"The planner returned a proposal outside its contract and it was "
                        f"refused rather than repaired: {exc.reason}")
                    return
                except ProviderError as exc:
                    self._finish_step(run, call, ok=False, provider_error=str(exc)[:300])
                    self._provider_failure(run, exc)
                    return

                run.budget.input_tokens = budget.input_tokens
                run.budget.output_tokens = budget.output_tokens
                run.budget.usd = budget.usd
                run.budget.llm_calls_exploration = budget.exploration_calls
                run.budget.llm_calls_recovery = budget.recovery_calls
                run.credential_tier = (proposal.completion.credential_tier.value
                                       if proposal.completion else run.credential_tier)
                self._finish_step(run, call, proposal=proposal.to_dict(),
                                  budget=budget.to_dict())
                self._store.save_run(run)

                if proposal.action == "abstain":
                    self._terminate(
                        run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                        f"The planner abstained rather than acting on a guess: "
                        f"{proposal.args.get('reason', '')}")
                    return
                if proposal.action == "finish":
                    break

                ctx.last_observed = ""
                outcome = await self._perform(ctx, proposal, recovery, families_tried)
                # An action whose result the model never sees is one it cannot learn from:
                # the first loop repeated a successful `extract` until the step budget ran
                # out, because nothing in its history said the extraction had worked.
                result = (f"ok: {ctx.last_observed[:120]!r}" if ctx.last_observed
                          else "ok") if outcome is None else outcome.value
                history.append(f"{proposal.action} {proposal.args} -> {result}")
                if outcome is None:
                    recovery = None
                    families_tried = []
                    if await self._goal_already_met(ctx, plan):
                        already_read = True
                        break
                    continue

                # Failed. The next call is a recovery call, from a separate reserve, and it
                # is told which families have already been spent.
                families_tried.append(proposal.strategy.value if proposal.strategy else "?")
                recovery = {"cause": outcome.value, "families_tried": families_tried}
                if budget.recovery_calls >= settings.budgets.recovery_calls:
                    self._terminate(
                        run, TerminalStatus.FAILED, FailureClass.BUDGET_EXHAUSTED,
                        f"The recovery budget ({settings.budgets.recovery_calls} calls) is "
                        f"exhausted after diagnosed cause '{outcome.value}'. The bar was "
                        f"not lowered to finish: the run fails instead.")
                    return

            if plan.read_step is not None and not already_read:
                await plan.read_step(ctx)
            await self._verify(run, ctx)

    async def _goal_already_met(self, ctx: ExecutionContext, plan: Plan) -> bool:
        """Whether the loop can stop, decided by code against the frozen postcondition.

        The model is unreliable at recognising that it is done, and unreliability here is
        paid for in quota: on the category listing it reached the right page on its first
        action and then spent five more calls re-extracting it. Asking the model to try
        harder is not a fix — it is the same judgement that was wrong, phrased differently.

        So the postcondition answers instead, and only on its own terms. Both conditions
        come from the object frozen before browsing: every action it declared has been
        observed, and the plan's own read step now yields every claim it requires. Nothing
        the model says is consulted.

        This can only end a run earlier. It cannot make a wrong answer pass: the verifier
        still re-extracts from the stored artifact and compares against the same frozen
        postcondition, so a premature stop produces a loud mismatch rather than a quiet
        success.
        """
        if plan.read_step is None:
            return False
        required = [c.name for c in plan.postcondition.claims if not c.optional]
        if not required:
            return False
        if self._verifier.missing_actions(ctx.run, plan.postcondition):
            # Reading the value before the declared interaction happened is the shortcut
            # S-4.4 exists to catch, not a reason to stop.
            return False
        try:
            await plan.read_step(ctx)
        except Exception:  # noqa: BLE001 - a probe that fails just means "not yet"
            ctx.candidate = {}
            return False
        candidate = ctx.candidate or {}
        if not all(candidate.get(name) not in (None, "", [], {}) for name in required):
            return False
        self._finish_step(ctx.run, self._step(
            ctx.run, StepKind.NOTE,
            "The frozen postcondition is satisfiable from this page: every declared action "
            "has been observed and every required claim reads. The loop stops here rather "
            "than spending further model calls.",
            claims_present=required))
        return True

    async def _perform(self, ctx: ExecutionContext, proposal: Proposal,
                       recovery: dict[str, Any] | None,
                       families_tried: list[str]) -> DiagnosedCause | None:
        """Execute one proposed action. Returns None on success, or the diagnosed cause.

        Whether this step counts as a retry or a recovery is decided here and recorded on
        the entry: same family as the failure it follows is a retry, a different family is
        a recovery (S-7.1, S-7.2). Neither is inferred later from the shape of the trace.
        """
        run = ctx.run
        family_to = proposal.strategy
        family_from = None
        if recovery and families_tried:
            previous = families_tried[-1]
            family_from = next((f for f in StrategyFamily if f.value == previous), None)

        # Which control was actually acted on, in a form the required-action check can
        # read. The postcondition declares required actions as selectors; the planner works
        # in refs, and without resolving one to the other every planner-driven run fails as
        # `required_action_skipped` while having taken exactly the right action.
        identity = await self._identify(ctx, str(proposal.args.get("ref", "")))
        entry = self._step(
            run, _STEP_KINDS.get(proposal.action, StepKind.NOTE),
            f"{proposal.action} {proposal.args.get('ref', proposal.args.get('key', ''))}"
            f" — {proposal.why[:120]}",
            selector=identity.selector(),
            element=identity.to_dict(), proposed_by="planner", args=proposal.args)
        entry.family_from = family_from
        entry.family_to = family_to
        if recovery:
            entry.diagnosed_cause = next(
                (c for c in DiagnosedCause if c.value == recovery["cause"]),
                DiagnosedCause.NONE)

        try:
            observed = await self._apply(ctx, proposal)
        except Exception as exc:  # noqa: BLE001 - the failure is the input to a diagnosis
            cause = await self._diagnose(ctx, proposal, exc)
            self._finish_step(run, entry, ok=False, error=f"{type(exc).__name__}: {exc}"[:300],
                              diagnosed_cause=cause.value,
                              repair=("recovery" if entry.is_recovery else
                                      "retry" if entry.is_retry else "first attempt"))
            self._store.save_trace_entry(run.id, entry)
            return cause

        self._finish_step(run, entry, url=ctx.page.url, observed=observed,
                          repair=("recovery" if entry.is_recovery else
                                  "retry" if entry.is_retry else "first attempt"))
        self._store.save_trace_entry(run.id, entry)
        ctx.last_observed = observed
        return None

    async def _identify(self, ctx: ExecutionContext, ref: str) -> ElementIdentity:
        """Resolve a ref to durable identity, as `app.identity` defines it."""
        return await identify(ctx.page, ref)

    async def _click(self, ctx: ExecutionContext, selector: str, summary: str, *,
                     navigates: bool = False) -> None:
        """A scripted click that records what it clicked, not just how it found it.

        A CSS selector is our spelling of an element, not the page's. When only the selector
        was recorded, the declared target of a required action had to match one vocabulary
        on the scripted path and a different one on the planned path — which is the
        asymmetry that made the required-action check fail runs that did exactly the right
        thing. Both paths now record the identity the page publishes.
        """
        identity = ElementIdentity(recorded_as=(selector,))
        handle = await ctx.page.query_selector(selector)
        if handle is not None:
            try:
                identity = ElementIdentity.from_browser(await handle.evaluate(COLLECT_JS))
            except Exception:  # noqa: BLE001 - identification is diagnostic, not load-bearing
                pass
        entry = self._step(ctx.run, StepKind.CLICK, summary, selector=selector,
                           element=identity.to_dict())
        if navigates:
            async with ctx.page.expect_navigation(wait_until="domcontentloaded"):
                await ctx.page.click(selector)
        else:
            await ctx.page.click(selector)
        self._finish_step(ctx.run, entry, final_url=ctx.page.url)

    async def _apply(self, ctx: ExecutionContext, proposal: Proposal) -> str:
        """The only place a proposed action touches the browser. The allow-list is closed:
        anything not named here never had a way to run."""
        page = ctx.page
        args = proposal.args
        ref = str(args.get("ref", ""))
        selector = f"[data-agent-ref='{ref}']"
        timeout = 8_000
        if proposal.action == "click":
            await page.click(selector, timeout=timeout)
        elif proposal.action == "fill":
            await page.fill(selector, str(args.get("text", "")), timeout=timeout)
        elif proposal.action == "select":
            await page.select_option(selector, str(args.get("value", "")), timeout=timeout)
        elif proposal.action == "press":
            await page.keyboard.press(str(args.get("key", "")))
        elif proposal.action == "wait_for":
            await page.wait_for_selector(selector, state="visible", timeout=timeout)
        elif proposal.action == "extract":
            # The model may point at where a value lives; it does not get to report the
            # value. The candidate the run is judged on comes from the plan's read step.
            # `attached` rather than `visible`: the verifier re-reads from the stored DOM,
            # so a value that is present but off-screen is still a legitimate target.
            element = await page.wait_for_selector(selector, state="attached",
                                                   timeout=timeout)
            text = (await element.inner_text())[:200] if element else ""
            await page.wait_for_timeout(150)
            return text
        else:
            raise RuntimeError(f"unreachable action {proposal.action!r}")
        # An action that navigates leaves the next view — and the next snapshot — describing
        # a document that is still arriving. A fixed pause was enough only because several
        # more steps always followed; it stopped being enough the moment the loop learned to
        # stop early.
        try:
            await page.wait_for_load_state("load", timeout=5_000)
        except Exception:  # noqa: BLE001 - not settling is a diagnosis, not a crash
            pass
        await page.wait_for_timeout(150)
        return ""

    async def _diagnose(self, ctx: ExecutionContext, proposal: Proposal,
                        exc: Exception) -> DiagnosedCause:
        """A named cause from the closed set (S-7.6).

        "The step threw an exception" is not a diagnosis, so the page is asked what is
        actually true: is the element there at all, is it disabled, is something on top of
        it. The exception text is the last resort, not the first.
        """
        ref = str(proposal.args.get("ref", ""))
        selector = f"[data-agent-ref='{ref}']"
        text = f"{type(exc).__name__}: {exc}".lower()
        try:
            handle = await ctx.page.query_selector(selector)
            if handle is None:
                return DiagnosedCause.ELEMENT_ABSENT
            if not await handle.is_visible():
                return DiagnosedCause.NOT_YET_RENDERED
            if not await handle.is_enabled():
                return DiagnosedCause.NOT_INTERACTABLE
        except Exception:  # noqa: BLE001 - diagnosis must not fail the run itself
            pass
        if "intercepts pointer events" in text:
            return DiagnosedCause.OBSCURED_BY_OVERLAY
        if "strict mode violation" in text or "resolved to" in text:
            return DiagnosedCause.AMBIGUOUS_MATCH
        if "timeout" in text:
            return DiagnosedCause.NOT_YET_RENDERED
        if "navigation" in text:
            return DiagnosedCause.NAVIGATION_BLOCKED
        return DiagnosedCause.CONTENT_CHANGED

    def _provider_failure(self, run: Run, exc: ProviderError) -> None:
        """S-11.16: a provider that cannot serve the pinned model fails the run rather than
        quietly substituting another one."""
        self._terminate(
            run, TerminalStatus.BLOCKED, exc.failure_class,
            f"{exc.message} The pinned model is not substituted when it is unavailable: a "
            f"silent fallback would make every recorded score unreproducible.")

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
        reduced view (A7.4) — which is why the whole thing is kept.

        The document is settled first. A snapshot taken mid-parse is a *plausible* artifact —
        it is real markup from the real page — and everything downstream will treat it as
        the whole page. Capturing nine of twenty listing rows and then verifying against
        them is how an incomplete answer becomes an authoritative one.
        """
        try:
            await ctx.page.wait_for_load_state("load", timeout=5_000)
        except Exception:  # noqa: BLE001 - a page that never settles is still evidence
            log.debug("page did not reach load state before capture: %s", ctx.page.url)
        html_text = await ctx.page.content()
        # The homepage demonstrations are pinned: a grader arriving two weeks after
        # deployment must not find that the first screen is three expired links (A11.3).
        ref = ctx.store.put_artifact(
            ctx.run.id, f"dom:{label}", html_text.encode("utf-8"),
            source_url=ctx.page.url, media_type="text/html",
            pinned=ctx.run.pre_executed)
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
        ("wiki_special", ("what links here", "pages that link to", "special:")),
        ("wiki_sort", ("sort the", "sorted by", "sort by", "s&p 500 table",
                       "constituents table")),
        ("wiki_expand", ("expand the", "collapsed navbox", "navbox", "collapsible")),
        ("book_detail", ("light in the attic", "upc", "product detail")),
        ("book_category", ("nonfiction", "category listing", "second page of results")),
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
        # The mutation seed and the planner request are metadata about *how* to run the
        # task, not part of what is being asked. Left in, `seed mu6-overlay` makes every
        # task look like an overlay task and the router abstains for a reason that has
        # nothing to do with the request.
        low = self._strip_directives(task.lower())
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
        low = self._strip_directives(task.lower())
        seed = self._seed(task.lower())
        if name == "wiki_special":
            return self._plan_wiki_special(low)
        if name == "wiki_sort":
            return self._plan_wiki_sort(low)
        if name == "wiki_expand":
            return self._plan_wiki_expand(low)
        if name == "book_detail":
            return self._plan_book_detail(low)
        if name == "book_category":
            return self._plan_book_category(low)
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
    def _strip_directives(low: str) -> str:
        stripped = re.sub(r"\bseed[: ]+[a-z0-9-]+", " ", low)
        return SCRIPT_MARKER.sub(" ", PLANNER_MARKER.sub(" ", stripped))

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
        low = Executor._strip_directives(low).strip()
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
                    pc, (open_form, fill_and_submit, read_results),
                    entry_url=self._url("/", seed),
                    terms=("search", "product name", str(term or ""), "results"),
                    read_step=read_results)

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

        read = self._read_visible_page(target)
        return Plan("GS-2", f"Fixture pagination to page {target} (no URL change)",
                    pc, (open_browse, advance, read),
                    entry_url=self._url("/browse", seed),
                    terms=("next", "page", "products"), read_step=read)

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
                    pc, (open_gated, probe_blocked, dismiss_and_act, read_code),
                    entry_url=self._url("/gated", seed),
                    terms=("dismiss", "close", "reference code", "product code",
                           "before you continue"),
                    read_step=read_code)

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

    # ---- real sites (OP-6, OP-7) ------------------------------------------------
    #
    # Nothing below is site-specific machinery: the relations are the same ones the fixture
    # uses. What is site-specific is *data* — which URL, which label, which container — and
    # that lives in the frozen postcondition, where it is visible and hashed, rather than in
    # the reducer or the planner where it would be quietly deciding answers.

    def _plan_wiki_sort(self, low: str) -> Plan:
        """OP-4: sort a sortable wikitable by a named column, read the resulting top row.

        The trap this operation exists for: descending order takes *two* clicks on the
        header, and one click produces a completely reasonable ordering of the wrong kind.
        Nothing about the run looks wrong afterwards — a real table, really sorted, really
        read. So the postcondition does not assume what a click produces. It freezes the
        direction it wants and compares it against the table's own statement of how it is
        ordered, which is the only reading that is not our own assumption echoed back.
        """
        column = "GICS Sector"
        pc = Postcondition(
            goal=("On the Wikipedia list of S&P 500 companies, sort the constituents table "
                  "by GICS Sector in descending order, then report the symbol and the "
                  "sector of the row that ends up at the top."),
            operation="OP-4",
            target_url=WIKI_SP500,
            inputs={"sort_column": column, "direction": "descending"},
            required_actions=(
                RequiredAction("click", column,
                               "the ordering is produced client-side; there is no URL that "
                               "reaches it, so the interaction is the capability being "
                               "claimed", times=2),
            ),
            claims=(
                ClaimSpec("sort_state", column, Relation.SORT_STATE, "sort_state",
                          container=CONSTITUENTS),
                ClaimSpec("top_symbol", "Symbol", Relation.TABLE_COLUMN_CELL, "code",
                          container=CONSTITUENTS),
                ClaimSpec("top_sector", column, Relation.TABLE_COLUMN_CELL, "text",
                          container=CONSTITUENTS),
            ),
        )

        async def open_article(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, WIKI_SP500)
            await ctx.page.wait_for_selector("#constituents th.headerSort", timeout=15_000)

        async def sort_descending(ctx: ExecutionContext) -> None:
            selector = f'{CONSTITUENTS}//th[normalize-space(.)="{column}"]'
            for ordinal in ("first", "second"):
                await self._click(ctx, selector,
                                  f"Click the {column!r} header ({ordinal} click)")
                await ctx.page.wait_for_timeout(400)

        async def read_top_row(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "constituents-sorted")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               "Read the top row of the sorted table", label_anchor=column)
            values = await ctx.page.evaluate(
                r"""(column) => {
                    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
                    const table = document.querySelector('#constituents');
                    const heads = [...table.querySelectorAll('tr th')];
                    const at = name => heads.findIndex(
                      h => h.textContent.replace(/\s+/g, ' ').trim() === name);
                    const head = heads[at(column)];
                    const row = table.querySelector('tr:has(td)');
                    const cell = i => (row.cells[i] || {}).textContent || '';
                    const cls = (head.className || '').toLowerCase();
                    return {
                      sort_state: {column,
                        direction: head.getAttribute('aria-sort') ||
                          (cls.includes('headersortdown') ? 'descending' :
                           cls.includes('headersortup') ? 'ascending' : 'unsorted'),
                        column_index: at(column)},
                      top_symbol: norm(cell(at('Symbol'))),
                      top_sector: norm(cell(at(column)))};
                }""", column)
            ctx.candidate = values
            self._finish_step(ctx.run, entry, **{k: str(v)[:120] for k, v in values.items()})

        return Plan("OP-4", "wikipedia sortable table, descending sort", pc,
                    (open_article, sort_descending, read_top_row),
                    entry_url=WIKI_SP500,
                    terms=(column, "Symbol", "Security", "constituents"),
                    read_step=read_top_row)

    def _plan_wiki_expand(self, low: str) -> Plan:
        """OP-5: expand a collapsed navbox and read a value out of it.

        A4.2 applies and is not glossed over: the collapsed content is present in the DOM
        beforehand, so this is not shortcut-proof by construction. What is verified is the
        state transition — the collapsed marker must be gone from the stored artifact — plus
        a value bound to its label inside the expanded box. The claim is "declared and
        trace-verified", not "impossible to bypass".
        """
        group = "Energy"
        pc = Postcondition(
            goal=("On the Wikipedia list of S&P 500 companies, expand the collapsed S&P 500 "
                  "companies navbox at the foot of the article and report the constituents "
                  "listed under its Energy group."),
            operation="OP-5",
            target_url=WIKI_SP500,
            inputs={"group": group},
            required_actions=(
                RequiredAction("click", "show",
                               "the navbox is collapsed on load and its toggle is the only "
                               "way to open it"),
            ),
            claims=(
                ClaimSpec("still_collapsed", "the navbox's collapsed marker",
                          Relation.ELEMENT_ABSENT, "boolean",
                          container=COLLAPSED_NAVBOX),
                ClaimSpec("energy_group", group, Relation.TABLE_ROW_CELL, "text"),
            ),
        )

        async def open_article(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, WIKI_SP500)
            await ctx.page.wait_for_selector(NAVBOX_TOGGLE, timeout=15_000)

        async def expand(ctx: ExecutionContext) -> None:
            await self._click(ctx, NAVBOX_TOGGLE, "Expand the collapsed navbox")
            await ctx.page.wait_for_timeout(500)

        async def read_group(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "navbox-expanded")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               "Read the labelled group from the expanded navbox",
                               label_anchor=group)
            # `textContent`, not `innerText`. Verification re-reads the stored artifact with
            # lxml, which has no layout and therefore no rendered text; a cell holding a
            # list of inline links renders with no separators and parses with them. Reading
            # it the way the verifier will is the difference between a real mismatch and a
            # mismatch about whitespace.
            cell = await ctx.page.query_selector(
                f"//tr[th[normalize-space(.)='{group}']]/td[1]")
            text = norm_ws(await cell.evaluate("el => el.textContent")) if cell else None
            ctx.candidate = {"still_collapsed": True, "energy_group": text}
            self._finish_step(ctx.run, entry, energy_group=(text or "")[:120])

        return Plan("OP-5", "wikipedia collapsed navbox, expanded", pc,
                    (open_article, expand, read_group),
                    entry_url=WIKI_SP500,
                    terms=(group, "show", "S&P 500 companies", "navbox"),
                    read_step=read_group)

    def _plan_book_detail(self, low: str) -> Plan:
        """OP-7: open a product detail page from a listing and read a labelled field."""
        pc = Postcondition(
            goal=("Open 'A Light in the Attic' from the Poetry category listing and report "
                  "its UPC, availability and price excluding tax from the product "
                  "information table."),
            operation="OP-7",
            target_url=BOOK_DETAIL_URL,
            inputs={"title": "A Light in the Attic"},
            required_actions=(
                RequiredAction("click", "a-light-in-the-attic",
                               "the detail page is reached from the listing, and the "
                               "navigation is the capability being claimed"),
            ),
            claims=(
                ClaimSpec("upc", "UPC", Relation.TABLE_ROW_CELL, "text"),
                ClaimSpec("availability", "Availability", Relation.TABLE_ROW_CELL, "text"),
                ClaimSpec("price_excl_tax", "Price (excl. tax)", Relation.TABLE_ROW_CELL,
                          "money_gbp"),
            ),
        )

        async def open_listing(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, BOOK_CATEGORY_POETRY)

        async def open_detail(ctx: ExecutionContext) -> None:
            await self._click(ctx, "h3 a[title='A Light in the Attic']",
                              "Open the product from the listing", navigates=True)

        async def read_detail(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "product-detail")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               "Read the labelled product information rows",
                               label_anchor="UPC")
            values = {}
            for name, label in (("upc", "UPC"), ("availability", "Availability"),
                                ("price_excl_tax", "Price (excl. tax)")):
                cell = await ctx.page.query_selector(
                    f"//th[normalize-space()='{label}']/following-sibling::td[1]")
                values[name] = (await cell.inner_text()).strip() if cell else None
            ctx.candidate = values
            self._finish_step(ctx.run, entry, **values)

        return Plan("OP-7", "books.toscrape product detail, labelled field", pc,
                    (open_listing, open_detail, read_detail),
                    entry_url=BOOK_CATEGORY_POETRY,
                    terms=("UPC", "Availability", "Product Information",
                           "A Light in the Attic"),
                    read_step=read_detail)

    def _plan_book_category(self, low: str) -> Plan:
        """OP-6: page through a category listing and report list-level facts."""
        pc = Postcondition(
            goal=("On the books.toscrape Nonfiction category listing, go to the second "
                  "page of results and report the titles shown there, together with the "
                  "listing's own result count."),
            operation="OP-6",
            target_url=BOOK_CATEGORY_NONFICTION_P2,
            inputs={"page": 2},
            required_actions=(
                RequiredAction("click", "next",
                               "the second page is reached by paging, and paging is the "
                               "capability being claimed"),
            ),
            claims=(
                ClaimSpec("result_counter", "N results - showing X to Y",
                          Relation.COUNTER_ECHO, "counter"),
                ClaimSpec("items", "product listing entries", Relation.LIST_ENUMERATION,
                          "text_list",
                          container='//article[contains(@class,"product_pod")]//h3/a'),
            ),
        )

        async def open_category(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, BOOK_CATEGORY_NONFICTION)

        async def page_forward(ctx: ExecutionContext) -> None:
            await self._click(ctx, "li.next a", "Click 'next' to the second page",
                              navigates=True)

        async def read_listing(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "category-page-2")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               "Read the listing counter and the titles on this page",
                               label_anchor="results")
            counter = await ctx.page.query_selector("form.form-horizontal")
            text = norm_ws((await counter.inner_text()).strip()) if counter else ""
            m = re.search(r"(\d+)\s+results?(?:\s*[-\u2013]\s*showing\s+(\d+)\s+to\s+(\d+))?",
                          text, re.I)
            titles = await ctx.page.eval_on_selector_all(
                "article.product_pod h3 a", "els => els.map(e => e.getAttribute('title'))")
            ctx.candidate = {
                "result_counter": ({"count": int(m.group(1)), "term": None,
                                    "showing": [int(m.group(2)), int(m.group(3))]}
                                   if m and m.group(2) else
                                   {"count": int(m.group(1)), "term": None} if m else {}),
                "items": titles,
            }
            self._finish_step(ctx.run, entry, counter_text=text, titles=titles)

        return Plan("OP-6", "books.toscrape category listing, paged", pc,
                    (open_category, page_forward, read_listing),
                    entry_url=BOOK_CATEGORY_NONFICTION,
                    terms=("results", "showing", "next", "Nonfiction"),
                    read_step=read_listing)

    def _plan_wiki_special(self, low: str) -> Plan:
        """A task a person would reasonably ask, on a path a real site forbids.

        `en.wikipedia.org/robots.txt` Disallows `/wiki/Special:` for the wildcard group.
        "Which pages link to this article" is answered at `Special:WhatLinksHere`, so the
        task is ordinary and useful and we still do not fetch it — the refusal cites the
        matched rule and the group it came from, which is what makes it checkable by someone
        who does not trust us.

        The fixture's own Disallowed hook demonstrates the same rule against a site we
        control. This is the version where the site is not ours and the rule is not one we
        wrote.
        """
        target = f"{WIKI_SPECIAL}{WIKI_SP500.rsplit('/', 1)[-1]}"
        pc = Postcondition(
            goal=("List the Wikipedia pages that link to the list of S&P 500 companies, "
                  "which the site answers at Special:WhatLinksHere."),
            operation="OP-robots",
            target_url=target,
            inputs={},
            claims=(),
        )

        async def attempt(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, target)

        return Plan("OP-robots", "wikipedia Special: namespace (robots-Disallowed)",
                    pc, (attempt,), entry_url=target)

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

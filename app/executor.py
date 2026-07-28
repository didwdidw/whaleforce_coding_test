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
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlsplit

from lxml import html as lxml_html
from playwright.async_api import BrowserContext, Page

from app import egress
from app.browser import BrowserSupervisor, BrowserUnavailable
from app.config import settings
from app.coverage import CoverageLedger
from app.identity import COLLECT_JS, ElementIdentity, identify, normalise
from app.models import (
    DiagnosedCause, FailureClass, Run, RunState, StepKind, TerminalStatus, Tier, TraceEntry,
)
from app.models import StrategyFamily
from app.planner import Planner, Proposal, ProposalRejected, ResponseTruncated
from app.postcondition import (
    AbsenceMode, ClaimSpec, Postcondition, Relation, RequiredAction,
)
from app.records import (
    GATE_OPERATIONS, HOST_IN_TASK, POLICY_ROUTES, PROMISED_RECORDS, RECORD_BY_ROUTE,
    URL_IN_TASK, GateOperation, PromisedRecord, host_key, named_site, resolve_entry,
    site_aliases,
)
from app.provider import Provider, ProviderError, RunBudget
from app.verifier import frozen_input_drift
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
    # A19.5. The refusals go into Chinese before the capabilities do, deliberately: the
    # alternative is a build that declines an English "log into my brokerage account" and
    # attempts the same sentence in Chinese, which is worse than being English-only.
    (r"(登入|登陆|登录|註冊|注册|我的帳[戶号]|我的账[户号]|帳號密碼|账号密码|密碼|密码)",
     "authentication or a login flow"),
    (r"(券商|銀行帳[戶户]|银行账[户号]|我的(投資組合|投资组合|訂單|订单|購物車|购物车|"
     r"信箱|郵件|邮件|收件匣))", "private or personal data"),
    (r"(購買|购买|下[單单]|結帳|结账|付款|加入(購物車|购物车)|訂(位|房|票)|订(位|房|票)|"
     r"預訂|预订|訂閱|订阅)", "a transaction or a state change"),
    (r"(發表(評論|留言)|发表(评论|留言)|留下(評價|评价)|刪除|删除|寄(信|郵件|邮件)|"
     r"發送訊息|发送消息)", "writing to a third party"),
    (r"(驗證碼|验证码)", "an anti-bot challenge"),
)


#: How an undeclared task names where to start. An explicit URL first; otherwise a bare
#: hostname, which is how people actually write one ("on www.gutenberg.org, find…").
#: Parentheses are part of the path often enough to matter — Wikipedia disambiguates with
#: them — so a closing one is kept when the URL opened it. Cutting it produced a URL that
#: 404s, and the run then spent model calls recovering from our own truncation. Both
#: patterns live in `app.records` now, with the site names the verifier also has to read.

#: Words a goal is never *about*, so the reducer is not told to keep the page around them.
GOAL_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "onto", "its", "it's",
    "tell", "show", "find", "read", "get", "give", "list", "what", "which", "how", "many",
    "much", "does", "did", "are", "was", "were", "you", "your", "please", "then", "there",
    "then", "about", "page", "site", "website", "com", "org", "www", "http", "https",
})

# Words that are never a search term on their own.
STOPWORDS = frozenset({
    "the", "a", "an", "for", "it", "this", "that", "all", "any", "some", "our", "my",
    "catalogue", "catalog", "fixture", "products", "product", "items", "item", "page",
})

#: Asking for the answer instead of finding it. The hook is also robots-Disallowed, so the
#: refusal cites a rule rather than a preference.
TESTHOOK_PATH = "/__testhook__/ground-truth"

#: A question of the form "is there any X that …". Answering it with a list of what is
#: there is not an answer; absence has to be proven (Amendment 3).
ABSENCE_QUESTION = re.compile(
    r"\b(is|are)\s+there\s+any\b|\bdoes\s+any\b|\bany\s+\w+\s+(priced|costing|"
    r"cheaper|more expensive)\b|\bis\s+any\b")

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
WIKI_ARTICLE_BASE = "https://en.wikipedia.org/wiki/"
WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CONSTITUENTS = '//table[@id="constituents"]'
WIKI_SPECIAL = "https://en.wikipedia.org/wiki/Special:"
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
    #: The markup of the element the last `extract` pointed at.
    last_fragment: str = ""

    def deadline_exceeded(self) -> bool:
        return self.run.budget.elapsed_seconds > settings.budgets.wall_clock_seconds


def _compare(value: float | None, predicate: dict[str, Any]) -> bool:
    """The same comparison the verifier will make, used only to record what the run saw.
    The verdict is the verifier's; this is what goes in the trace so a disagreement between
    the two is visible rather than silent."""
    if value is None:
        return False
    op, target = predicate.get("op"), predicate.get("value")
    return {">": value > target, ">=": value >= target,
            "<": value < target, "<=": value <= target}.get(op, False)


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
            # Matching an operation's keywords is not the same as being the instance of it
            # we can execute. A13.1 requires the tier to match what the run actually does,
            # and a task we will send down the generic path is not a declared run.
            plan = self._select_plan(task)
            if plan is not None and not self.plan_answers_task(task, plan.postcondition):
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
        run.budget.ended_at = run.finished_at
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

        foreign = self.names_a_site_we_do_not_serve(run.task)
        operation, candidates, hits = ("generic", [], {}) if foreign else self.route(run.task)
        plan = (self._plan_generic(run.task) if foreign else
                self._select_plan(run.task) if operation else None)

        mismatch = self.plan_answers_task(run.task, plan.postcondition) if plan else ""
        if mismatch:
            entry = self._step(run, StepKind.NOTE,
                               f"The {plan.operation} plan does not answer this task",
                               operation=plan.operation, reason=mismatch)
            self._finish_step(run, entry, ok=False)
            plan, operation, candidates, hits = None, None, [], {}
            run.explanation = mismatch
        if plan is None and len(candidates) > 1:
            # Two promised operations match, so which one was asked for is genuinely
            # unanswerable. Refusing to choose is the decision; it is not "no script".
            entry = self._step(run, StepKind.NOTE,
                               f"Routing matched {len(candidates)} operations",
                               candidates=candidates, markers=hits)
            self._finish_step(run, entry, ok=False)
            self._terminate(
                run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                f"This task matches more than one operation ({', '.join(candidates)}), so "
                f"which one was asked for is ambiguous. Choosing one would produce an "
                f"answer to a question that may not have been asked, so the run stopped "
                f"before browsing. Rephrase to name a single operation.")
            return

        if plan is None:
            # Not a promised record. It is attempted anyway, by the generic loop — "we have
            # no script for this" is a fact about us, never a policy refusal of the task.
            plan = self._plan_generic(run.task)
            entry = self._step(
                run, StepKind.NOTE,
                f"No promised record matches; attempting as {Tier.EXPERIMENTAL.value}"
                if plan else "No promised record matches and no entry point was named",
                candidates=candidates, markers=hits,
                entry_url=plan.entry_url if plan else "")
            self._finish_step(run, entry, ok=plan is not None)
            if plan is None:
                self._terminate(
                    run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                    (f"This task resembles a promised operation, but {mismatch}. Running "
                     f"it anyway would answer a neighbouring question and report it as "
                     f"verified. The task also names no URL to attempt generically, so "
                     f"there is nowhere else to begin — name one and it will be attempted "
                     f"best-effort as an experimental run."
                     if mismatch else
                     "This task names no page or site to start from, and no promised "
                     "operation recognises it, so there is nowhere to begin. Picking a "
                     "starting page the task never named would answer a question nobody "
                     "asked. Name a URL or a site — for example \"on example.org, …\" — and "
                     "it will be attempted best-effort as an experimental run."))
                return
            if not self._provider.configured():
                self._terminate(
                    run, TerminalStatus.BLOCKED, FailureClass.PROVIDER_ERROR,
                    "A task outside the promised records is driven entirely by the model, "
                    "and no provider credential is readable, so there is no deterministic "
                    "path to fall back to. The promised operations are unaffected.")
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
        if plan.operation == "generic":
            # There is no script for a site nobody declared; that is what makes it generic.
            return True, "undeclared task, which only the generic loop can attempt"
        if asked_for_script:
            return False, "deterministic path requested as the comparison baseline"
        if not plan.entry_url or not plan.postcondition.claims:
            # Nothing for a model to plan toward: a plan with no claims is a policy
            # demonstration, and driving it with the model spends quota to reach a refusal
            # that was decided before the first fetch.
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

    @staticmethod
    def _absorb(run: Run, budget: RunBudget) -> None:
        """Copy what the provider has charged so far onto the run.

        Called on every way out of a model call, not only the one that succeeds: a call
        that produced a truncated or refused proposal has still been made and still been
        billed, and a run that reports zero calls for it is reporting a budget that is not
        the budget it spent.
        """
        run.budget.input_tokens = budget.input_tokens
        run.budget.output_tokens = budget.output_tokens
        run.budget.usd = budget.usd
        run.budget.llm_calls_exploration = budget.exploration_calls
        run.budget.llm_calls_recovery = budget.recovery_calls

    def _freeze(self, run: Run, plan: Plan) -> None:
        """Serialise and hash the postcondition before anything is browsed (S-4.12).

        The site the task named is stamped in here rather than by each plan: it is read from
        the task, it is the same reading for every plan, and a constraint that twelve plan
        builders each have to remember is a constraint that one of them will not.
        """
        plan.postcondition = replace(plan.postcondition, named_site=named_site(run.task))
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
                except ResponseTruncated as exc:
                    # Our output allowance, not a defect in our code and not a model that
                    # broke its contract. Naming it `internal_error` blamed the wrong thing
                    # and sent anyone reading the histogram looking for a bug.
                    self._absorb(run, budget)
                    self._finish_step(run, call, ok=False, truncated=exc.reason,
                                      output_cap_per_call=(
                                          settings.budgets.max_output_tokens_per_call),
                                      budget=budget.to_dict())
                    self._terminate(
                        run, TerminalStatus.FAILED, FailureClass.OUTPUT_TRUNCATED,
                        f"{exc.reason} The per-call output allowance is "
                        f"{settings.budgets.max_output_tokens_per_call} tokens and the "
                        f"model's deliberation shares it. Both calls are charged to this "
                        f"run's budget. The run stops here rather than guessing what the "
                        f"cut-off reply was going to say.")
                    return
                except ProposalRejected as exc:
                    # Outside the contract. Recorded and refused, never repaired into
                    # something plausible.
                    self._absorb(run, budget)
                    self._finish_step(run, call, ok=False, rejected=exc.reason,
                                      response_head=exc.raw)
                    self._terminate(
                        run, TerminalStatus.FAILED, FailureClass.INTERNAL_ERROR,
                        f"The planner returned a proposal outside its contract and it was "
                        f"refused rather than repaired: {exc.reason}")
                    return
                except ProviderError as exc:
                    self._absorb(run, budget)
                    self._finish_step(run, call, ok=False, provider_error=str(exc)[:300])
                    self._provider_failure(run, exc)
                    return

                self._absorb(run, budget)
                run.credential_tier = (proposal.completion.credential_tier.value
                                       if proposal.completion else run.credential_tier)
                self._finish_step(run, call, proposal=proposal.to_dict(),
                                  budget=budget.to_dict())
                self._store.save_run(run)

                if proposal.action == "abstain":
                    await self._abstain(ctx, plan, step,
                                        str(proposal.args.get("reason", "")), history)
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

    async def _abstain(self, ctx: ExecutionContext, plan: Plan, step: int, reason: str,
                       history: list[str]) -> None:
        """Stop without answering, and say enough for the stop to be checkable (A2.2).

        Three things, all of them observations rather than adjectives: the step it stopped
        at, the page state it was looking at when it stopped, and which part of the frozen
        postcondition could not be reached. Generic text is not an abstention; it is a
        refusal wearing one's clothes, and it is indistinguishable from a defect.

        The failure class is `postcondition_unmet`, not `policy_refused`. Nothing about
        policy stopped this run — it browsed, it looked, and it could not get there.
        """
        run = ctx.run
        try:
            title = (await ctx.page.title())[:120]
        except Exception:  # noqa: BLE001 - a page that cannot report is still a state
            title = "(page title unavailable)"
        url = ctx.page.url
        await self._capture(ctx, f"abstained-step-{step}")
        unmet = ", ".join(c.name for c in plan.postcondition.claims) or "the declared goal"
        entry = self._step(run, StepKind.NOTE, f"Abstained at step {step}",
                           reason=reason, url=url, title=title,
                           steps_taken=history[-5:], unmet=unmet)
        self._finish_step(run, entry, ok=False)
        self._terminate(
            run, TerminalStatus.UNSUPPORTED, FailureClass.POSTCONDITION_UNMET,
            f"Stopped at step {step} without answering, rather than guessing. "
            f"Reason given: {reason or '(none stated)'}. "
            f"Last observed page: {title!r} at {url}. "
            f"Unverified part of the frozen postcondition: {unmet}. "
            f"Actions taken before stopping: "
            f"{'; '.join(history[-5:]) if history else 'none'}. "
            f"A snapshot of the page as it was at that moment is stored with this run.")

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
        # Present is not the same as right. Every required claim reads on page 1 of a
        # listing, so "read the last page" stopped on the first one and failed for a
        # reason the loop had already been told: the frozen inputs disagreed with what was
        # on screen. The same drift check the verifier runs decides it here too.
        for spec in plan.postcondition.claims:
            value = candidate.get(spec.name)
            if value is not None and frozen_input_drift(spec, value, plan.postcondition):
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
                          fragment=ctx.last_fragment if proposal.action == "extract" else "",
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
            # The markup of what was pointed at, kept on the trace. An undeclared run has no
            # scripted read step, so this fragment is where its candidate comes from — read
            # by code, from the live page, at the moment the model pointed.
            ctx.last_fragment = ((await element.evaluate("el => el.outerHTML"))[:40_000]
                                 if element else "")
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
        # After the document settles, not before: a title that redirects still reports the
        # requested URL at `domcontentloaded`, and the trace then shows no redirect while
        # every artifact carries the canonical URL — which reads as a run that wandered.
        try:
            await ctx.page.wait_for_load_state("load", timeout=5_000)
        except Exception:  # noqa: BLE001 - a page that never settles is still a page
            pass
        self._finish_step(run, nav, status=response.status if response else None,
                          final_url=ctx.page.url)
        return await self._landed_somewhere_real(ctx, run, nav)

    #: Pages that answer 200 and are not the page anybody asked for. A title assembled from
    #: a sentence lands on one of these, and without this the run proceeds to look for its
    #: anchors on a page that says the article does not exist — an abstention blamed on the
    #: locator when the entry point was wrong (A25.1).
    ABSENT_PAGE_MARKERS: tuple[tuple[str, str], ...] = (
        ("div.noarticletext", "Wikipedia has no article with this exact title"),
        ("#noarticletext", "Wikipedia has no article with this exact title"),
    )

    async def _landed_somewhere_real(self, ctx: ExecutionContext, run: Run, nav) -> bool:
        for selector, why in self.ABSENT_PAGE_MARKERS:
            try:
                if await ctx.page.locator(selector).count():
                    self._finish_step(run, nav, ok=False, error=why)
                    self._terminate(
                        run, TerminalStatus.BLOCKED, FailureClass.SITE_UNAVAILABLE,
                        f"{why}: {ctx.page.url}. The starting page was derived from the "
                        f"task's own words, and the words did not name a page that "
                        f"exists. Continuing would look for the answer on a page whose "
                        f"only content is that there is no such page.")
                    return False
            except Exception:  # noqa: BLE001 - a selector that cannot run is not a finding
                continue
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
        # One capture, one step. The accessibility tree is a second artifact of the *same*
        # observation, and giving it its own trace entry charged the run a second step for
        # it — every trace entry costs one, so A24.6 quietly halved the browsing headroom
        # of a capture-heavy run and turned a working task into `budget_exhausted`.
        aria = await self._capture_accessibility(ctx, label)
        entry = self._step(ctx.run, StepKind.SNAPSHOT, f"Snapshot captured: {label}",
                           artifact=ref.to_dict(),
                           accessibility_artifact=aria[0], accessibility_note=aria[1])
        entry.artifact_id = ref.id
        self._finish_step(ctx.run, entry)
        ctx.evidence_artifact = ref.id
        return ref.id

    async def _capture_accessibility(self, ctx: ExecutionContext,
                                     label: str) -> tuple[dict[str, Any] | None, str]:
        """Store the accessibility tree beside the DOM (A24.6).

        An F1 locator is a semantic role and an accessible name, and this is the corpus
        those are read from. Stored markup is not a substitute: the name a browser computes
        can come from a label, an `aria-labelledby` several elements away, or the element's
        own text, and re-deriving it from the DOM afterwards means re-implementing the
        browser. Without this, an F1 claim — and any recovery or healing that passed through
        F1 — cannot be re-derived from the evidence, which is what §4 rests on.

        Returns the artifact and a note. A page that will not produce one says so in the
        snapshot step: an accessibility artifact missing with nothing recorded would read
        as a page that had no accessible structure (A11.8).
        """
        try:
            snapshot = await ctx.page.locator("body").aria_snapshot()
        except Exception as exc:  # noqa: BLE001 - the DOM is already stored either way
            return None, f"not captured: {type(exc).__name__}: {exc}"
        ref = ctx.store.put_artifact(
            ctx.run.id, f"aria:{label}", snapshot.encode("utf-8"),
            source_url=ctx.page.url, media_type="text/plain",
            pinned=ctx.run.pre_executed)
        return ref.to_dict(), ""

    # ---- routing ---------------------------------------------------------------

    #: Operations that exist only on our own fixture. Reachable only when the task names
    #: the fixture (A24.4) — its data is invented, so an unnamed question answered from it
    #: is fabricated data returned as an answer.
    FIXTURE_ONLY_ROUTES: frozenset[str] = frozenset(
        {"testhook", "notes", "overlay", "absence", "paginate", "search"})

    # Every marker is distinctive to one operation. A bare "page" is not a marker: "the
    # gated page" would otherwise route an overlay task to the paginator, which then returns
    # a perfectly plausible pager reading for a task that asked for something else. A
    # mis-route that still produces an answer is worse than one that fails.
    # The promised operations carry Chinese markers as well (A19.4). Matching is a
    # substring test, so CJK needs no word-boundary handling here — unlike the site alias
    # table, where `\b` never fires between 「維基百科」 and the 「的」 after it.
    ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("wiki_special", ("what links here", "pages that link to", "pages link to",
                          "special:",
                          "search page", "find articles", "wikipedia's search",
                          "特殊:", "連入頁面", "链入页面")),
        ("wiki_sort", ("sort the", "sorted by", "sort by", "s&p 500 table",
                       "constituents table",
                       "排序", "由大到小排", "由小到大排", "成分股表格")),
        ("wiki_expand", ("expand the", "collapsed navbox", "navbox", "collapsible",
                         "展開", "展开", "摺疊", "折叠", "收合")),
        ("book_absence", ("priced at", "priced over", "priced above", "or more",
                          "or above", "at least £", "more expensive than", "cheaper than",
                          "under £", "less than £",
                          "價格超過", "价格超过", "售價超過", "售价超过", "貴於", "貴過",
                          "便宜於", "便宜过", "低於 £", "低于 £", "高於 £", "高于 £")),
        ("book_detail", ("light in the attic", "upc", "product detail",
                         "product information", "product page for",
                         "商品詳情", "商品详情", "產品資訊", "产品信息", "商品頁", "商品页")),
        ("book_category", ("nonfiction", "category", "page of results",
                           "pages of results",
                           "非小說", "非小说", "分類", "分类", "類別", "类别",
                           "頁的結果", "页的结果")),
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
        for name, markers in self.routes_for(task):
            matched = [m for m in markers if m in low]
            if matched:
                hits[name] = matched
        if len(hits) > 1:
            hits = self._apply_precedence(hits)
        return (next(iter(hits)) if len(hits) == 1 else None), list(hits), hits

    #: Pairs that legitimately co-occur, with the reason one reading is the question and
    #: the other is only the route to it. This is not a tiebreak for guessing: an
    #: undeclared pair still abstains, which is what routing does when it does not know.
    PRECEDENCE: tuple[tuple[str, str, str], ...] = (
        ("book_detail", "book_category",
         "a task naming a specific product asks about that product; the category it sits "
         "in is how the product is reached, not what is being asked"),
        ("book_absence", "book_category",
         "a question about whether anything matches names a category to say where to look, "
         "not to ask for a listing; answering it with the listing answers a question that "
         "was not asked"),
        ("book_absence", "book_detail",
         "the same, for a price question that happens to name a title"),
        ("absence", "book_absence",
         "a price question that names the fixture is a fixture task; a task naming "
         "books.toscrape never reaches the fixture's markers at all, and a task naming "
         "neither reaches no fixture marker either (A24.4), because the site restricts the "
         "routes before precedence is consulted"),
    )

    @classmethod
    def _apply_precedence(cls, hits: dict[str, list[str]]) -> dict[str, list[str]]:
        remaining = dict(hits)
        for winner, loser, _why in cls.PRECEDENCE:
            if winner in remaining and loser in remaining:
                remaining.pop(loser)
        return remaining

    def _select_plan(self, task: str) -> Plan | None:
        name, _, _ = self.route(task)
        if name is None:
            return None
        low = self._strip_directives(task.lower())
        seed = self._seed(task.lower())
        if name == "wiki_special":
            return self._plan_wiki_special(low)
        if name == "wiki_sort":
            # The original casing, not `low`: the column header and the article title are
            # matched against the page, which spells them the way the page spells them.
            return self._plan_wiki_sort(self._strip_directives(task))
        if name == "wiki_expand":
            return self._plan_wiki_expand(self._strip_directives(task))
        if name == "book_detail":
            # The original casing, not `low`: the title is matched against the listing's
            # own `title` attribute, which is case-sensitive, so a lowercased title finds
            # nothing and the run pages to its bound looking for a book that is on page one.
            return self._plan_book_detail(self._strip_directives(task))
        if name == "book_absence":
            return self._plan_book_absence(low)
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
        predicate = {"field": "price_gbp", "op": ">", "value": threshold}
        pc = Postcondition(
            goal=f"Determine whether any catalogue item is priced over £{threshold}",
            operation="GS-4",
            target_url=self._url("/browse", seed).split("?")[0],
            inputs={"seed": seed, "predicate": predicate},
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
            # The comparison the verifier will re-apply, not a second spelling of it. Two
            # rules that agree by coincidence stop agreeing the first time either is edited.
            matches = [r["sku"] for r in rows
                       if (p := re.search(r"£\s*([0-9.]+)", r["text"] or ""))
                       and _compare(float(p.group(1)), predicate)]
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

    #: How a person names a Wikipedia article in a sentence.
    ARTICLE_PHRASE = (
        re.compile(r"wikipedia (?:article|page) (?:for|on|about) ['\"]?([^,.'\"]+)"),
        re.compile(r"wikipedia (list of [^,.'\"]+)"),
        re.compile(r"(list of [^,.'\"]+?) (?:on |from )?wikipedia"),
        re.compile(r"([\w&'()-]+(?:[.\s]+[\w&'()-]+)*?\.?)\s+"
                   r"wikipedia\s+(?:article|page)"),
        # 「在維基百科的 List of S&P 500 companies 條目裡」 (A19.4). The title itself stays
        # in the language the article is published in — it is matched against the page, and
        # the promised record is the English Wikipedia.
        re.compile(r"維基百科(?:的|上的)?\s*([\w&'()\- ]+?)\s*"
                   r"(?:條目|頁面|列表|那一?頁|裡|中|,|，|。|$)"),
        re.compile(r"维基百科(?:的|上的)?\s*([\w&'()\- ]+?)\s*"
                   r"(?:条目|页面|列表|那一?页|里|中|,|，|。|$)"),
    )

    #: The sort key, as the task names it. A quoted phrase wins: it is the one spelling the
    #: user has told us is exact.
    SORT_COLUMN = (
        re.compile(r"sort(?:ed)?\s+(?:the\s+\w+\s+table\s+)?by\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"by\s+(?:the\s+)?['\"]([^'\"]+)['\"]\s+column"),
        re.compile(r"by\s+(?:the\s+)?([A-Za-z][\w ]*?)\s+column"),
        re.compile(r"sort(?:ed)?\s+(?:the\s+[\w ]*?table\s+)?by\s+([A-Za-z][\w ]*?)"
                   r"(?=\s+(?:ascending|descending|newest|oldest|alphabetically|"
                   r"largest|smallest|and|,|$))"),
        # "sort alphabetically by country" — the ordering word comes first as often as not.
        re.compile(r"(?:alphabetically|numerically|ascending|descending)\s+by\s+"
                   r"(?:the\s+)?([A-Za-z][\w /]*?)(?=\s*(?:,|\.|and|$))"),
        # 「依 GICS Sector 由大到小排序」 / 「按 CIK 排序」. The column keeps the spelling
        # the task gave it, because it is matched against a header the page renders.
        re.compile(r"(?:依照|依|按照|按|以)\s*([A-Za-z][\w &/-]*?)\s*"
                   r"(?:欄|列|這一?欄|由大到小|由小到大|遞增|遞減|递增|递减|升冪|降冪|"
                   r"升序|降序|排序|排列)"),
    )

    #: Ordering words, each mapped to the direction the *table* will report.
    DIRECTION_WORDS: tuple[tuple[str, str], ...] = (
        ("descending", "descending"), ("newest first", "descending"),
        ("largest first", "descending"), ("highest first", "descending"),
        ("z to a", "descending"), ("reverse alphabetical", "descending"),
        ("ascending", "ascending"), ("alphabetically", "ascending"),
        ("oldest first", "ascending"), ("smallest first", "ascending"),
        ("lowest first", "ascending"), ("a to z", "ascending"),
        ("由大到小", "descending"), ("從大到小", "descending"), ("遞減", "descending"),
        ("递减", "descending"), ("降冪", "descending"), ("降序", "descending"),
        ("由小到大", "ascending"), ("從小到大", "ascending"), ("遞增", "ascending"),
        ("递增", "ascending"), ("升冪", "ascending"), ("升序", "ascending"),
    )

    @classmethod
    def wikipedia_article(cls, task: str) -> str:
        """The article the task names, as a URL, or "" if it names none resolvably.

        A phrase, not a search: `Special:Search` is robots-Disallowed and guessing an
        article we were not given is how a run answers a question nobody asked. When the
        task names no article this returns "", the plan is not built, and the run says so.
        """
        explicit = cls.resolve_entry(task)
        if "wikipedia.org/wiki/" in explicit:
            return explicit
        low = task.lower()
        for pattern in cls.ARTICLE_PHRASE:
            match = pattern.search(low)
            if not match:
                continue
            start, end = match.span(1)
            phrase = norm_ws(task[start:end]).strip()
            # "On the Apple Inc. Wikipedia page" — the leading words belong to the
            # sentence, not to the title, and an article called "On the Apple Inc." does
            # not exist. Wrong is better than approximately right here: the run would
            # navigate somewhere real and answer about it.
            while True:
                head = phrase.split(" ", 1)
                if len(head) == 2 and head[0].lower() in (
                        "on", "in", "from", "the", "a", "an", "open", "at", "for", "about"):
                    phrase = head[1]
                    continue
                break
            # And the trailing noun, for the same reason. Only the leading words were
            # stripped, so "the List of S&P 500 companies **article**" resolved to
            # `/wiki/List_of_S%26P_500_companies_article` — a real navigation to a page
            # that does not exist, and the phrasing our own limitations list published as
            # the way to make the task succeed (A25.1).
            while True:
                tail = phrase.rsplit(" ", 1)
                if len(tail) == 2 and tail[1].lower().strip(".,'\"") in (
                        "article", "page", "entry", "wikipedia", "wiki"):
                    phrase = tail[0]
                    continue
                break
            if not phrase or len(phrase) < 3:
                continue
            title = phrase[0].upper() + phrase[1:]
            return f"{WIKI_ARTICLE_BASE}{quote(title.replace(' ', '_'), safe='_()')}"
        return ""

    @classmethod
    def sort_parameters(cls, task: str) -> tuple[str, str]:
        """(column, direction) as the task states them; either may be "" if it does not.

        Matching is case-insensitive but the column keeps the casing the task gave it: it
        is compared against a header the page renders, and lowercasing it first meant no
        header ever matched.
        """
        column = ""
        for pattern in cls.SORT_COLUMN:
            match = pattern.search(task.lower())
            if match:
                start, end = match.span(1)
                column = norm_ws(task[start:end]).strip()
                break
        low = task.lower()
        direction = next((d for word, d in cls.DIRECTION_WORDS if word in low), "")
        return column, direction

    def _plan_wiki_sort(self, low: str) -> Plan | None:
        """OP-4: sort a sortable wikitable by a named column, read the resulting top row.

        The trap this operation exists for: descending order takes *two* clicks on the
        header, and one click produces a completely reasonable ordering of the wrong kind.
        Nothing about the run looks wrong afterwards — a real table, really sorted, really
        read. So the postcondition does not assume what a click produces. It freezes the
        direction it wants and compares it against the table's own statement of how it is
        ordered, which is the only reading that is not our own assumption echoed back.

        Article, column and direction all come from the task. They were constants, and the
        first harness run showed what that cost: "sort by CIK ascending" and "sort the GDP
        table alphabetically by country" both executed the canned S&P/GICS-descending plan
        and came back verified.
        """
        article = self.wikipedia_article(low)
        column, direction = self.sort_parameters(low)
        if not article or not column or not direction:
            return None

        # Which cell of the top row is wanted is not knowable in advance on an article
        # nobody declared, so the whole row is reported, each cell bound to its own column
        # header. That is a stronger binding than picking one column and hoping.
        pc = Postcondition(
            goal=(f"On {article}, sort the table by {column!r} in {direction} order, then "
                  f"report the row that ends up at the top with each cell bound to its "
                  f"column header."),
            operation="OP-4",
            target_url=article,
            inputs={"sort_column": column, "direction": direction},
            required_actions=(
                RequiredAction("click", column,
                               "the ordering is produced client-side; there is no URL that "
                               "reaches it, so the interaction is the capability being "
                               "claimed", times=2 if direction == "descending" else 1),
            ),
            claims=(
                ClaimSpec("sort_state", column, Relation.SORT_STATE, "sort_state"),
                ClaimSpec("top_row", column, Relation.TABLE_TOP_ROW, "row"),
            ),
        )

        clicks = 2 if direction == "descending" else 1

        async def open_article(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, article)
            try:
                await ctx.page.wait_for_selector("table.sortable th", timeout=15_000)
            except Exception:  # noqa: BLE001 - no sortable table is an answer, not a crash
                self._terminate(
                    ctx.run, TerminalStatus.UNSUPPORTED, FailureClass.POSTCONDITION_UNMET,
                    f"{article} has no sortable table, so there is nothing to sort by "
                    f"{column!r}. That is a fact about the article, not a failure to look.")

        async def sort_column(ctx: ExecutionContext) -> None:
            selector = (f'xpath=//table[contains(@class,"sortable")]'
                        f'//th[normalize-space(.)="{column}"]')
            if await ctx.page.query_selector(selector) is None:
                self._terminate(
                    ctx.run, TerminalStatus.UNSUPPORTED, FailureClass.POSTCONDITION_UNMET,
                    f"No sortable column on {article} is headed {column!r}. Sorting by a "
                    f"neighbouring column would answer a different question.")
                return
            for ordinal in range(clicks):
                await self._click(ctx, selector,
                                  f"Click the {column!r} header (click {ordinal + 1} of "
                                  f"{clicks}, for {direction} order)")
                await ctx.page.wait_for_timeout(400)

        async def read_top_row(ctx: ExecutionContext) -> None:
            await self._capture(ctx, "table-sorted")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               "Read the top row of the sorted table", label_anchor=column)
            values = await ctx.page.evaluate(
                r"""(column) => {
                    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
                    // The same rule the verifier uses: an exact header, or the single
                    // header the named one is a prefix of. A person writes "country"; the
                    // table says "Country/Territory". Reading it by a different rule than
                    // the one that will check it produces a mismatch about nothing.
                    const hit = (text, name) => text === name ||
                        text.toLowerCase().startsWith(name.toLowerCase());
                    const tables = [...document.querySelectorAll('table')];
                    const table = tables.find(t => [...t.querySelectorAll('tr th')]
                        .some(h => hit(norm(h.textContent), column)));
                    if (!table) return {};
                    const heads = [...table.querySelectorAll('tr th')];
                    const at = name => {
                      const exact = heads.findIndex(h => norm(h.textContent) === name);
                      if (exact >= 0) return exact;
                      const starts = heads.filter(
                        h => norm(h.textContent).toLowerCase()
                               .startsWith(name.toLowerCase()));
                      const unique = new Set(starts.map(h => norm(h.textContent)));
                      return unique.size === 1 ? heads.indexOf(starts[0]) : -1;
                    };
                    const head = heads[at(column)];
                    const cls = (head.className || '').toLowerCase();
                    const row = table.querySelector('tr:has(td)');
                    const cells = row ? [...row.cells] : [];
                    const top = {};
                    heads.forEach((h, i) => {
                      if (cells[i]) top[norm(h.textContent)] = norm(cells[i].textContent);
                    });
                    return {
                      sort_state: {column,
                        direction: head.getAttribute('aria-sort') ||
                          (cls.includes('headersortdown') ? 'descending' :
                           cls.includes('headersortup') ? 'ascending' : 'unsorted'),
                        column_index: at(column)},
                      top_row: top};
                }""", column)
            ctx.candidate = values
            self._finish_step(ctx.run, entry, **{k: str(v)[:200] for k, v in values.items()})

        return Plan("OP-4", f"wikipedia sortable table, {column} {direction}", pc,
                    (open_article, sort_column, read_top_row),
                    entry_url=article,
                    terms=(column, "sortable", "table"),
                    read_step=read_top_row)

    #: "the first collapsed box", "the second collapsible". Absent means the first one.
    NTH_COLLAPSIBLE = re.compile(r"\b(first|second|third|fourth|fifth)\b")

    #: The group inside an expanded box the task asks about, when it names one.
    GROUP_PHRASE = (
        re.compile(r"(?:the\s+)?['\"]([^'\"]+)['\"]\s+(?:row\s+)?group"),
        re.compile(r"(?:the\s+)?([A-Z][\w&. ]*?)\s+(?:row\s+)?group\b"),
    )

    def _plan_wiki_expand(self, task: str) -> Plan | None:
        """OP-5: expand a collapsed box on an article and read a value out of it.

        A4.2 applies and is not glossed over: the collapsed content is present in the DOM
        beforehand, so this is not shortcut-proof by construction. What is verified is the
        state transition — that box's collapsed marker must be gone from the stored
        artifact — plus a value bound to its label inside it. The claim is "declared and
        trace-verified", not "impossible to bypass".

        Which article and which box come from the task. They were constants, so "expand the
        first collapsed box on the Apple Inc. article" expanded a navbox on the S&P 500
        article instead and reported it as verified.
        """
        low = task.lower()
        article = self.wikipedia_article(task)
        if not article:
            return None
        nth = self.NTH_COLLAPSIBLE.search(low)
        index = {"first": 1, "second": 2, "third": 3, "fourth": 4,
                 "fifth": 5}.get(nth.group(1) if nth else "", 1)
        group = ""
        for pattern in self.GROUP_PHRASE:
            match = pattern.search(task)
            if match:
                group = norm_ws(match.group(1)).strip()
                break

        # The box's own collapsed marker, scoped to the one that was opened. Scoping
        # matters: an article with three collapsibles keeps two of them collapsed, and a
        # page-wide "no collapsed marker anywhere" check would fail every honest run.
        # Indexed among the *collapsible* boxes, not among the collapsed ones. Counting
        # collapsed boxes renumbers them the moment one opens, so box 1's marker check
        # started reading box 2 — which is still collapsed, correctly — and the state
        # transition it had just performed looked like it had not happened.
        collapsed_marker = (f'(//*[contains(@class,"mw-collapsible")])[{index}]'
                            f'[contains(@class,"mw-collapsed")]')

        claims = [ClaimSpec("still_collapsed", f"collapsed marker of box {index}",
                            Relation.ELEMENT_ABSENT, "boolean",
                            container=collapsed_marker)]
        if group:
            claims.append(ClaimSpec("group", group, Relation.TABLE_ROW_CELL, "text"))

        pc = Postcondition(
            goal=(f"On {article}, expand collapsed box {index} and report "
                  + (f"the entries listed under its {group!r} group."
                     if group else "that it is no longer collapsed.")),
            operation="OP-5",
            target_url=article,
            # The index is frozen as a parameter only when the task named one; box 1 is
            # where we start, not something the task asked for.
            inputs={**({"collapsible_index": index} if nth else {}),
                    **({"group": group} if group else {})},
            required_actions=(
                RequiredAction("click", "show",
                               "the box is collapsed on load and its toggle is the only "
                               "way to open it"),
            ),
            claims=tuple(claims),
        )

        toggle = (f'xpath=(//*[contains(@class,"mw-collapsible")]'
                  f'//*[contains(@class,"mw-collapsible-toggle")])[{index}]')

        async def open_article(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, article)
            try:
                await ctx.page.wait_for_selector(toggle, timeout=15_000)
            except Exception:  # noqa: BLE001 - no such box is an answer about the article
                self._terminate(
                    ctx.run, TerminalStatus.UNSUPPORTED, FailureClass.POSTCONDITION_UNMET,
                    f"{article} has no collapsed box number {index} to expand. That is a "
                    f"fact about the article, not a failure to look.")

        async def expand(ctx: ExecutionContext) -> None:
            await self._click(ctx, toggle, f"Expand collapsed box {index}")
            await ctx.page.wait_for_timeout(500)

        async def read_group(ctx: ExecutionContext) -> None:
            await self._capture(ctx, f"collapsible-{index}-expanded")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               "Read the expanded box", label_anchor=group or "expanded")
            values: dict[str, Any] = {"still_collapsed": True}
            if group:
                # `textContent`, not `innerText`. Verification re-reads the stored artifact
                # with lxml, which has no layout and therefore no rendered text; a cell of
                # inline links renders with no separators and parses with them. Reading it
                # the way the verifier will is the difference between a real mismatch and a
                # mismatch about whitespace.
                cell = await ctx.page.query_selector(
                    f"//tr[th[normalize-space(.)='{group}']]/td[1]")
                values["group"] = (norm_ws(await cell.evaluate("el => el.textContent"))
                                   if cell else None)
            ctx.candidate = values
            self._finish_step(ctx.run, entry, **{k: str(v)[:120] for k, v in values.items()})

        return Plan("OP-5", f"wikipedia collapsed box {index}, expanded", pc,
                    (open_article, expand, read_group),
                    entry_url=article,
                    terms=tuple(t for t in (group, "show", "navbox", "collapsible") if t),
                    read_step=read_group)

    #: Where a product is looked for when the task does not say which category it is in.
    #: The whole catalogue paginates from here, twenty to a page.
    BOOK_INDEX_URL = f"{BOOKS}/catalogue/page-1.html"
    #: How far the search will page before giving up and saying so. A bound, not a guess:
    #: the alternative to stopping is walking fifty pages for a title that may not exist,
    #: and a run that spends its whole budget looking is indistinguishable from one that
    #: found nothing.
    BOOK_SEARCH_PAGES = 6

    #: How a task names the product. A quoted title wins — it is the spelling the user has
    #: told us is exact.
    BOOK_TITLE = (
        re.compile(r"['\"\u2018\u201c]([^'\"\u2019\u201d]{3,80})['\"\u2019\u201d]"),
        re.compile(r"(?:product|book|detail) page for (?:the )?(.{3,80}?)"
                   r"(?=\s+(?:and|then|to|,|\.|$))", re.I),
        re.compile(r"\bopen (?:the )?(.{3,80}?)"
                   r"(?=\s+(?:from|and|then|product page|detail page|,|\.|$))", re.I),
        re.compile(r"the (?:upc|availability|price)[^,.?!]{0,30}? of (?:the )?(.{3,80}?)"
                   r"(?=\s*(?:,|\.|\?|$))", re.I),
        # 「的 A Light in the Attic 商品詳情」 — the title itself stays in the language the
        # site publishes it in, because it is matched against the listing (A19.4).
        re.compile(r"的\s*([A-Za-z0-9][^的，,。]{2,80}?)\s*"
                   r"(?:商品詳情|商品详情|產品資訊|产品信息|商品頁|商品页)"),
    )

    @classmethod
    def book_title(cls, task: str) -> str:
        """The product a task names, as the listing spells it, or "" if it names none."""
        stripped = cls._strip_directives(task)
        for pattern in cls.BOOK_TITLE:
            match = pattern.search(stripped)
            if match:
                return norm_ws(match.group(1)).strip(" '\"")
        return ""

    @staticmethod
    def _book_slug(title: str) -> str:
        """The slug books.toscrape builds its detail URLs from. Used for the required
        action's target so the check compares the same vocabulary the page publishes."""
        return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

    @classmethod
    def book_detail_url(cls, title: str) -> str:
        """The detail page, when we know it. The site's URLs carry an opaque id after the
        slug, so it is only knowable in advance for a product we have seen — for anything
        else the frozen target is the listing the run must reach it from, which is what the
        run is actually required to do."""
        if title.lower() == "a light in the attic":
            return BOOK_DETAIL_URL
        return cls.BOOK_INDEX_URL

    def _plan_book_detail(self, low: str) -> Plan:
        """OP-7: open a product detail page from a listing and read a labelled field.

        The record is `books.toscrape.com × open a product detail page and read a labelled
        field`; the *product* is a parameter of it (A18.1). This plan used to freeze that
        parameter — one title, one category URL, one selector — which made the published
        support matrix false for every other book on the site while reading as though it
        held for all of them (A25.2). A promised record has to hold for the values of its
        parameters or the promise is about one page rather than about an operation.
        """
        title = self.book_title(low)
        if not title:
            # No plan rather than a default. Falling back to a canned product would answer
            # about a book the task never named and verify it perfectly — the failure this
            # record was generalised to remove, reintroduced as a default value.
            return None
        listing = (BOOK_CATEGORY_POETRY if title.lower() == "a light in the attic"
                   else self.BOOK_INDEX_URL)
        pc = Postcondition(
            goal=(f"Open {title!r} from the books.toscrape listing and report its UPC, "
                  f"availability and price excluding tax from the product information "
                  f"table."),
            operation="OP-7",
            target_url=self.book_detail_url(title),
            inputs={"title": title},
            required_actions=(
                RequiredAction("click", self._book_slug(title),
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
            await self._navigate(ctx, listing)

        async def open_detail(ctx: ExecutionContext) -> None:
            selector = f"h3 a[title=\"{title}\"]"
            for page in range(self.BOOK_SEARCH_PAGES):
                if await ctx.page.query_selector(selector) is not None:
                    await self._click(ctx, selector,
                                      "Open the product from the listing", navigates=True)
                    return
                nxt = await ctx.page.query_selector("li.next a")
                if nxt is None:
                    break
                await self._click(ctx, "li.next a",
                                  f"Page forward looking for {title!r} "
                                  f"({page + 2} of at most {self.BOOK_SEARCH_PAGES})",
                                  navigates=True)
            self._terminate(
                ctx.run, TerminalStatus.UNSUPPORTED, FailureClass.POSTCONDITION_UNMET,
                f"{title!r} was not on any of the first {self.BOOK_SEARCH_PAGES} listing "
                f"pages, so the product page was never opened and nothing is reported. "
                f"The catalogue has no search, so a product is found by paging; naming the "
                f"category it is in, or its detail URL, reaches it directly.")

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

    #: Categories the sidebar offers. The listing names them; we do not invent any.
    CATEGORY_WORD = re.compile(
        r"\b(travel|mystery|historical fiction|fiction|nonfiction|non-fiction|romance|"
        r"humor|humour|childrens|children's|classics|poetry|science fiction|science|"
        r"philosophy|history|horror|music|business|thriller|biography|health|art|"
        r"food and drink|sequential art|young adult|new adult|fantasy|self help|"
        r"academic|autobiography|crime|psychology|politics|cultural|erotica|womens "
        r"fiction|sports and games|christian|spirituality|contemporary|paranormal|"
        r"suspense|default|add a comment|novels|short stories)\b")

    #: "the third page", "page 3", "the last page". Absent means the first page.
    PAGE_WORD = re.compile(r"\b(?:page\s+(\d+)|(\d+)(?:st|nd|rd|th)\s+page|"
                           r"(first|second|third|fourth|fifth|last)\s+page)\b")

    @classmethod
    def target_page(cls, low: str) -> int | str:
        """Which page of a listing the task asks for. A named page nobody asked for is the
        defect this whole gate exists for, so absence means the first page, not page two."""
        match = cls.PAGE_WORD.search(low)
        if not match:
            return 1
        if match.group(1) or match.group(2):
            return int(match.group(1) or match.group(2))
        word = match.group(3)
        return "last" if word == "last" else {
            "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}[word]

    #: How a price question is worded, and the comparison each wording means. Ordered so a
    #: two-word form is tried before the single word it contains.
    PRICE_OPERATORS: tuple[tuple[str, str], ...] = (
        (r"or\s+more", ">="), (r"or\s+above", ">="), (r"or\s+over", ">="),
        (r"at\s+least", ">="), (r"or\s+higher", ">="),
        (r"or\s+less", "<="), (r"at\s+most", "<="), (r"or\s+cheaper", "<="),
        (r"more\s+than", ">"), (r"more\s+expensive\s+than", ">"),
        (r"priced\s+over", ">"), (r"priced\s+above", ">"), (r"over", ">"), (r"above", ">"),
        (r"less\s+than", "<"), (r"cheaper\s+than", "<"), (r"under", "<"), (r"below", "<"),
    )

    @classmethod
    def price_predicate(cls, low: str) -> dict[str, Any] | None:
        """The comparison the task asked for, or nothing.

        Nothing is the important half: a price question whose threshold or direction cannot
        be read is not answered with a guessed one. "£60 or more" and "over £60" differ on
        exactly one book, and picking the wrong one produces a fully verifiable answer to a
        question nobody asked.
        """
        money = re.search(r"£\s*([0-9]+(?:\.[0-9]+)?)", low)
        if not money:
            return None
        threshold = float(money.group(1))
        after = low[money.end():]
        for pattern, op in cls.PRICE_OPERATORS:
            if re.search(rf"\b{pattern}\b", after) or re.search(
                    rf"\b{pattern}\b\s*£?\s*{re.escape(money.group(1))}", low):
                return {"field": "price_gbp", "op": op, "value": threshold}
        return None

    def _plan_book_absence(self, low: str) -> Plan:
        """XB-1 Mode B on a promised category: is there any book matching this price?

        Absence is only ever concluded from a positive proof (A3.1). The proof here is the
        listing's own results counter — A3.2 names that exact form, `"110 results - showing
        1 to 20."`, as a coverage anchor — checked against a full enumeration re-read from
        the stored artifact. Answering "no" because nothing was noticed is `unverified`, and
        stays that way.
        """
        category = (self.CATEGORY_WORD.search(low) or [None])[0]
        category = category.title() if isinstance(category, str) else "Poetry"
        predicate = self.price_predicate(low)
        readable = ({">=": "at or above", ">": "above",
                     "<=": "at or below", "<": "below"}.get(predicate["op"], "matching")
                    + f" £{predicate['value']}") if predicate else "matching"

        pc = Postcondition(
            goal=(f"On books.toscrape, determine whether any book in the {category} "
                  f"category is priced {readable}, by enumerating the whole category and "
                  f"proving coverage against the listing's own results count."),
            operation="OP-6",
            target_url=f"{BOOKS}/catalogue/category/books/",
            inputs={"category": category, "url_scope": "prefix", "predicate": predicate},
            required_actions=(
                RequiredAction("click", category,
                               "the category listing is reached from the sidebar, and the "
                               "navigation is the capability being claimed"),
            ),
            claims=(
                ClaimSpec("result_counter", "N results - showing X to Y",
                          Relation.COUNTER_ECHO, "counter"),
                ClaimSpec("items", "every product entry in the listing",
                          Relation.LIST_ENUMERATION, "sku_list",
                          container='//article[contains(@class,"product_pod")]'),
            ),
            absence=AbsenceMode.B_ENUMERATION,
            coverage_anchor="the category listing's own results count",
        )

        async def open_home(ctx: ExecutionContext) -> None:
            if predicate is None:
                self._terminate(
                    ctx.run, TerminalStatus.UNSUPPORTED, FailureClass.POLICY_REFUSED,
                    "The task asks whether any book matches a price, but the threshold or "
                    "the comparison could not be read from it. Choosing either would answer "
                    "a different question, so the run stopped before browsing.")
                return
            await self._navigate(ctx, f"{BOOKS}/index.html")

        async def open_category(ctx: ExecutionContext) -> None:
            selector = (f'xpath=//div[contains(@class,"side_categories")]//a'
                        f'[normalize-space(.)="{category}"]')
            await self._click(ctx, selector, f"Click the {category} category link",
                              navigates=True)

        async def enumerate_category(ctx: ExecutionContext) -> None:
            await self._capture(ctx, f"absence-{category.lower()}")
            entry = self._step(
                ctx.run, StepKind.EXTRACT,
                "Enumerate every listed book and read the listing's own result count",
                label_anchor="results")
            counter = await ctx.page.query_selector("form.form-horizontal")
            text = norm_ws((await counter.inner_text()).strip()) if counter else ""
            # The same parse the listing plan uses: the counter states "showing X to Y" when
            # the category spans pages, and reporting a shape the artifact does not have
            # fails the run on the counter instead of on the coverage question that matters.
            m = re.search(r"(\d+)\s+results?(?:\s*[-\u2013]\s*showing\s+(\d+)\s+to\s+(\d+))?",
                          text, re.I)
            # Read by the rule that will check it: the verifier identifies a listing entry
            # by the first nested `title`, so the run does too. Two rules that agree by
            # coincidence stop agreeing the first time either one is edited.
            rows = await ctx.page.eval_on_selector_all(
                "article.product_pod",
                "els => els.map(e => {const t = e.querySelector('[title]');"
                " return {title: t ? t.getAttribute('title') : null, text: e.innerText};})")
            items = []
            for row in rows:
                text = norm_ws(row["text"] or "")
                price = re.search(r"£\s*([0-9]+(?:\.[0-9]+)?)", text)
                items.append({"sku": norm_ws(row["title"] or "") or text or None,
                              "text": text,
                              "price_gbp": float(price.group(1)) if price else None})
            ctx.candidate = {
                "result_counter": ({"count": int(m.group(1)), "term": None,
                                    "showing": [int(m.group(2)), int(m.group(3))]}
                                   if m and m.group(2) else
                                   {"count": int(m.group(1)), "term": None} if m else {}),
                "items": items,
                # What the run itself concluded. Stating it is what lets the verifier
                # disagree; a plan that only ever asserts absence cannot be caught reading
                # the predicate backwards.
                "matches": [i["sku"] for i in items
                            if predicate and _compare(i["price_gbp"], predicate)],
            }
            self._finish_step(ctx.run, entry, counter_text=text, enumerated=len(items),
                              matches=[i["sku"] for i in items
                                       if predicate and _compare(i["price_gbp"], predicate)])

        return Plan("OP-6", f"books.toscrape {category}: is any book priced {readable}?",
                    pc, (open_home, open_category, enumerate_category),
                    entry_url=f"{BOOKS}/index.html",
                    terms=("results", "showing", category, "price", "£"),
                    read_step=enumerate_category)

    def _plan_book_category(self, low: str) -> Plan:
        """OP-6: reach a named category, page to the page the task asked for, and report
        that page's list-level facts.

        Every parameter here used to be a constant. The task named a category and a page and
        the plan ignored both, so "the last page of Nonfiction" was answered with page two
        and marked verified. What is frozen now is what the task said, and reaching a page
        it did not ask for shows up as the pager contradicting the frozen input.
        """
        category = (self.CATEGORY_WORD.search(low) or [None])[0]
        category = category.title() if isinstance(category, str) else "Nonfiction"
        page = self.target_page(low)
        # A page the task did not name is our landing page, not its request, and freezing
        # it would make the plan-answers-task gate demand the task say "first".
        named_page = bool(self.PAGE_WORD.search(low))

        required = [RequiredAction("click", category,
                                   "the category listing is reached from the sidebar, and "
                                   "the navigation is the capability being claimed")]
        if isinstance(page, int) and page > 1:
            required.append(RequiredAction(
                "click", "next", "each page beyond the first is reached by paging, and "
                                 "paging is the capability being claimed", times=page - 1))

        pc = Postcondition(
            goal=(f"On books.toscrape, open the {category} category listing, reach "
                  f"{'the last page' if page == 'last' else f'page {page}'} of results, and "
                  f"report the titles shown there together with the listing's own result "
                  f"count and pager position."),
            operation="OP-6",
            target_url=f"{BOOKS}/catalogue/category/books/",
            inputs={"category": category, "url_scope": "prefix",
                    **({"page": page} if named_page else {})},
            required_actions=tuple(required),
            claims=(
                ClaimSpec("result_counter", "N results - showing X to Y",
                          Relation.COUNTER_ECHO, "counter"),
                # A category with a single page has no pager, and demanding one would fail
                # a correct run for a fact about the category.
                ClaimSpec("pager", "Page N of M", Relation.PAGER_POSITION, "pager",
                          optional=(page == 1)),
                ClaimSpec("items", "product listing entries", Relation.LIST_ENUMERATION,
                          "text_list",
                          container='//article[contains(@class,"product_pod")]//h3/a'),
            ),
        )

        async def open_home(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, f"{BOOKS}/index.html")

        async def open_category(ctx: ExecutionContext) -> None:
            selector = (f'xpath=//div[contains(@class,"side_categories")]//a'
                        f'[normalize-space(.)="{category}"]')
            await self._click(ctx, selector, f"Click the {category} category link",
                              navigates=True)

        async def page_forward(ctx: ExecutionContext) -> None:
            clicked = 0
            while True:
                if isinstance(page, int) and clicked >= page - 1:
                    return
                if ctx.deadline_exceeded():
                    return
                nxt = await ctx.page.query_selector("li.next a")
                if nxt is None:
                    if isinstance(page, int) and clicked < page - 1:
                        self._terminate(
                            ctx.run, TerminalStatus.UNSUPPORTED,
                            FailureClass.POSTCONDITION_UNMET,
                            f"The {category} listing ends before page {page}: paging "
                            f"stopped after {clicked + 1} page(s) because no 'next' control "
                            f"remains. The page asked for does not exist, which is an "
                            f"answer about the site, not a failure to look.")
                    return
                await self._click(ctx, "li.next a",
                                  f"Click 'next' to page {clicked + 2}", navigates=True)
                clicked += 1

        async def read_listing(ctx: ExecutionContext) -> None:
            await self._capture(ctx, f"category-{category.lower()}")
            entry = self._step(ctx.run, StepKind.EXTRACT,
                               "Read the listing counter, the pager and the titles",
                               label_anchor="results")
            counter = await ctx.page.query_selector("form.form-horizontal")
            text = norm_ws((await counter.inner_text()).strip()) if counter else ""
            m = re.search(r"(\d+)\s+results?(?:\s*[-\u2013]\s*showing\s+(\d+)\s+to\s+(\d+))?",
                          text, re.I)
            pager_el = await ctx.page.query_selector("li.current")
            pager_text = norm_ws((await pager_el.inner_text()).strip()) if pager_el else ""
            pm = re.search(r"page\s+(\d+)\s+of\s+(\d+)", pager_text, re.I)
            titles = await ctx.page.eval_on_selector_all(
                "article.product_pod h3 a", "els => els.map(e => e.getAttribute('title'))")
            ctx.candidate = {
                "result_counter": ({"count": int(m.group(1)), "term": None,
                                    "showing": [int(m.group(2)), int(m.group(3))]}
                                   if m and m.group(2) else
                                   {"count": int(m.group(1)), "term": None} if m else {}),
                "pager": ({"page": int(pm.group(1)), "total": int(pm.group(2)),
                           "items": None} if pm else None),
                "items": titles,
            }
            self._finish_step(ctx.run, entry, counter_text=text, pager=pager_text,
                              titles=titles)

        return Plan("OP-6", f"books.toscrape {category} listing, page {page}", pc,
                    (open_home, open_category, page_forward, read_listing),
                    entry_url=f"{BOOKS}/index.html",
                    terms=("results", "showing", "next", category, "Page", "of"),
                    read_step=read_listing)

    # ---- does this plan answer the question that was asked? ---------------------

    #: Frozen inputs that describe *how* a run is executed rather than what was asked.
    INTERNAL_INPUTS = frozenset({"seed", "entry_url", "url_scope", "binding"})

    #: A person writes "the second page"; a postcondition freezes `2`.
    ORDINALS: dict[int, tuple[str, ...]] = {
        1: ("first", "1st"), 2: ("second", "2nd"), 3: ("third", "3rd"),
        4: ("fourth", "4th"), 5: ("fifth", "5th"),
    }

    @classmethod
    def _input_synonyms(cls) -> dict[str, dict[str, tuple[str, ...]]]:
        """Task wordings that legitimately produce a frozen value it does not contain.

        A frozen input is not always a quotation: "newest first" is frozen as `descending`
        because that is what the table will say about itself. Built from the same table the
        parser uses, so a new wording cannot be accepted by one and rejected by the other.
        """
        directions: dict[str, list[str]] = {}
        for word, direction in cls.DIRECTION_WORDS:
            directions.setdefault(direction, []).append(word)
        return {"direction": {k: tuple(v) for k, v in directions.items()},
                # The category a promised listing is fixed to, named in Chinese (A19.4).
                # Without it a correctly routed Chinese task is refused for not naming the
                # parameter it did name.
                "category": {"Nonfiction": ("非小說", "非小说", "非虛構", "非虚构")}}

    @staticmethod
    def _task_names(task: str, spelling: str) -> bool:
        """Whether a task names a value, in the writing system the task used.

        Two readings, because one cannot serve both. `normalise` keeps ASCII words only —
        that is what makes `sort` not match `resort` — and it drops CJK entirely, so a
        Chinese spelling checked against a normalised haystack can never match: the alias
        table would be present and fire on nothing, which is how a correctly routed Chinese
        task came back refused for not naming the parameter it had named. Chinese is also
        written without spaces, so a substring is the right boundary there.
        """
        if not spelling.isascii():
            return spelling.lower() in task.lower()
        needle = normalise(spelling)
        return bool(needle) and f" {needle} " in f" {normalise(task)} "

    @classmethod
    def plan_answers_task(cls, task: str, pc: Postcondition) -> str:
        """"" if the plan's frozen parameters are ones the task actually named.

        The gap this closes was found by the first harness run and it is the exact failure
        this system exists to prevent. A task asking to sort by **CIK ascending** matched
        the sort operation's keywords, was handed the canned plan for **GICS Sector
        descending**, executed it perfectly, verified it against its own frozen
        postcondition, and came back `succeeded_verified`. Every structural check passed,
        because every structural check compares the run against the plan — and the plan was
        never compared against the task. Four dev cases were being answered that way.

        So: a frozen input the task does not name is an assumption, and an assumption
        presented as an answer is the whole problem. Not naming one is not a refusal of the
        task; it means this canned instance is not the one being asked for, and the run
        goes to the generic path or stops and says which parameter it could not honour.
        """
        # A yes/no question about whether anything matches needs a plan entitled to prove
        # absence (Amendment 3). A listing plan answers it with a listing — every claim
        # verified, the question untouched. The parameter check below cannot see this,
        # because a task naming a category does name the category.
        if ABSENCE_QUESTION.search(task.lower()) and pc.absence is AbsenceMode.NONE:
            return ("the task asks whether anything matches a predicate, and this plan "
                    "cannot prove absence — it would report a listing instead of an answer")

        for key, value in (pc.inputs or {}).items():
            # Scalars only. A structure is something the plan derived from the task with
            # its own parser — the absence predicate is built from the threshold the task
            # gave — and demanding its serialisation appear in the sentence is nonsense.
            if (key in cls.INTERNAL_INPUTS or isinstance(value, bool)
                    or not isinstance(value, (str, int, float))):
                continue
            spellings = [str(value)]
            spellings += list(cls._input_synonyms().get(key, {}).get(str(value), ()))
            if isinstance(value, float) and value.is_integer():
                spellings.append(str(int(value)))
            if isinstance(value, int):
                spellings += list(cls.ORDINALS.get(value, ()))
            if not any(cls._task_names(task, s) for s in spellings if s):
                return (f"the plan is fixed to {key}={value!r}, which this task does not "
                        f"ask for")
        return ""

    # ---- the undeclared path (A13.2) -------------------------------------------

    #: Reading a site out of a task is not a routing decision, so it does not live here:
    #: the verifier has to make the same reading independently (A17.1) and must not import
    #: the router to do it. These stay as names on the executor because they are the router's
    #: vocabulary, and they resolve to one implementation in `app.records`.
    resolve_entry = staticmethod(resolve_entry)
    site_aliases = staticmethod(site_aliases)
    named_site = staticmethod(named_site)

    @classmethod
    def names_a_site_we_do_not_serve(cls, task: str) -> str:
        """The task points at a host that is neither the fixture nor a promised record's.

        Keyword routing is deliberately loose — `find` is a marker for the fixture search —
        and that is fine while every task is one of ours. It stops being fine the moment a
        task names somewhere else: "on www.gutenberg.org, **find** the Science Fiction
        bookshelf" was captured by the fixture's search plan and refused for having no
        search term, on a site the plan had never heard of. Where the task says to go
        settles it before any keyword does.
        """
        host = cls.named_site(task)
        if not host:
            return ""
        ours = {host_key(urlsplit(settings.fixture_base_url).netloc)}
        ours |= {host_key(r.site) for r in PROMISED_RECORDS}
        return "" if host in ours else cls.resolve_entry(task)

    @classmethod
    def routes_for(cls, task: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Which operations may match, given where the task says it is.

        A task naming a promised site may only reach that site's promised operations. The
        fixture's markers are broad on purpose — it is our own test site and its tasks are
        phrased however we phrase them — and left unrestricted they swallowed real ones:
        "page forward to the third page" on books.toscrape reached the *fixture* paginator,
        which then failed on a site the task never mentioned.
        """
        host = cls.named_site(task)
        if not host:
            # A task naming no site may not be answered by the fixture (A24.4). The
            # fixture's catalogue is data we invented, so answering an unnamed question
            # from it hands back fabricated data as an answer — the silent failure this
            # project is built against, in its most severe form. A promised record on a
            # public site is different: its data is the site's, and a described-but-unnamed
            # entry point is a separate question (A18.3).
            return tuple(r for r in cls.ROUTES if r[0] not in cls.FIXTURE_ONLY_ROUTES)
        allowed = {route for r in PROMISED_RECORDS if host_key(r.site) == host
                   for route in (r.route, *r.extra_routes)}
        allowed |= set(POLICY_ROUTES.get(host, ()))
        if allowed:
            return tuple(r for r in cls.ROUTES if r[0] in allowed)
        if host == host_key(urlsplit(settings.fixture_base_url).netloc):
            return cls.ROUTES
        # A named site that is neither promised nor the fixture has no site-specific
        # operation here, and falling back to the whole table let the fixture's own routes
        # claim it: "Use Wikipedia's search page to find X" was answered by searching our
        # fixture, finding nothing, and reporting a verified absence. Nothing in that run
        # was wrong except which site it was on.
        return ()

    @staticmethod
    def goal_terms(task: str) -> tuple[str, ...]:
        """What the reducer should keep the page around. The task's own content words —
        on a site nobody has declared, they are the only signal we have about relevance."""
        words = [w for w in re.findall(r"[A-Za-z0-9'£$€.-]{3,}", task)
                 if w.lower().strip("'.-") not in GOAL_STOPWORDS]
        seen: dict[str, None] = {}
        for word in words:
            seen.setdefault(word.strip("'.-"), None)
        return tuple(seen)[:12]

    #: Where the asking starts. The parts a task wants are what follows the last of these,
    #: because "open X and tell me A and B" asks for two things and does not ask for X.
    ASK_VERB = re.compile(
        r"\b(?:tell me|tell us|what (?:is|are|was|were)|read|give me|report|show me|"
        r"extract|find out)\b", re.I)
    #: Splitting on these over-counts before it under-counts, deliberately. A part too many
    #: makes a correct run `partial`, which is loud; a part too few is a value dropped in
    #: silence, which is the failure this project is built against.
    ASK_SPLIT = re.compile(r",\s*|\s+and\s+|\s+plus\s+|\s+as well as\s+", re.I)
    #: More than this and the sentence is prose, not a list of values.
    MAX_ASKED_PARTS = 4

    @classmethod
    def asked_for_parts(cls, task: str) -> tuple[str, ...]:
        """The distinct values a task asks for, in the order it asks for them.

        Deliberately a small parser and not a model call: how many things were asked for
        decides whether a run may be called a success, and that decision must not be made
        by the component whose answer it is grading.
        """
        tail = task.strip()
        last = None
        for last in cls.ASK_VERB.finditer(tail):
            pass
        if last:
            tail = tail[last.end():]
        parts: list[str] = []
        for chunk in cls.ASK_SPLIT.split(tail):
            chunk = chunk.strip(" .?!'\"\n\t")
            # A fragment carrying its own verb is another instruction, not another value.
            if len(chunk) < 3 or cls.ASK_VERB.search(chunk):
                continue
            if chunk.lower() not in {p.lower() for p in parts}:
                parts.append(chunk)
        if not parts or len(parts) > cls.MAX_ASKED_PARTS:
            # Nothing recognisable, or a sentence long enough that splitting it is guessing.
            # One claim is the old behaviour and it is the conservative end here: the run
            # still has to bind its single answer to a label or it does not succeed.
            return (task.strip(),)
        return tuple(parts)

    @staticmethod
    def claim_names(parts: tuple[str, ...]) -> tuple[str, ...]:
        """`answer` when there is one, `answer_1…n` when there are several — so a
        single-part task's evidence keeps the shape every earlier run recorded."""
        if len(parts) == 1:
            return ("answer",)
        return tuple(f"answer_{i}" for i in range(1, len(parts) + 1))

    def _plan_generic(self, task: str) -> Plan | None:
        """A postcondition for a task on a site we have never seen (A13.2).

        It is deliberately weaker than a promised record's and deliberately not absent. What
        is frozen before browsing: the site the evidence must come from, and that whatever
        the run reports has to be re-readable by code from a label the run located in the
        stored artifact. What is not frozen — cannot be — is which label that will be.

        A run that finds the answer somewhere with no structural binding fails to verify and
        abstains. That is the intended behaviour, not a shortfall to be patched: an answer
        with nothing holding it to the page is the plausible-but-wrong result this whole
        system is built to refuse.
        """
        entry = self.resolve_entry(task)
        if not entry:
            return None
        # One claim per part the task asked for (A25.3). A single unnamed claim let a live
        # request for "UPC and availability" verify the UPC, drop availability without a
        # word, and return `succeeded_verified` — S-5.2 forbids presenting a partial result
        # as a success, and an empty postcondition is how that prohibition gets bypassed
        # without anyone writing the word `partial`. A13.2.3 permits a weaker postcondition
        # on this tier; it does not permit an absent one.
        parts = self.asked_for_parts(task)
        claims = tuple(ClaimSpec(name=name, label="", relation=Relation.LOCATED_LABEL,
                                 value_type="string")
                       for name in self.claim_names(parts))
        asked = ("\n".join(f"  {name}: {part}"
                           for name, part in zip(self.claim_names(parts), parts))
                 if len(parts) > 1 else "")
        pc = Postcondition(
            goal=(f"{task.strip()}\n\nTo complete this task you MUST emit `extract` "
                  f"pointing at the element that holds the value, with `label_anchor` set "
                  f"to the exact visible text of the label it is bound to, before you "
                  f"finish. Code re-reads the value from that label; a run that finishes "
                  f"without one cannot be verified and is scored as a failure."
                  + (f"\n\nThis task asks for {len(parts)} separate values. Emit one "
                     f"`extract` for each, in this order, each with its own "
                     f"`label_anchor`:\n{asked}\nAnswering some of them and stopping is "
                     f"a partial result, not a success." if len(parts) > 1 else "")),
            operation="generic",
            target_url=entry,
            inputs={"entry_url": entry, "url_scope": "site",
                    "asked_for": list(parts),
                    "binding": "value re-read by code from a label located in the artifact"},
            claims=claims,
        )
        return Plan("generic", f"undeclared task on {urlsplit(entry).netloc}", pc, (),
                    entry_url=entry, terms=self.goal_terms(task),
                    read_step=self._read_generic)

    async def _read_generic(self, ctx: ExecutionContext) -> None:
        """The candidate for an undeclared run: the value code reads, beside the label the
        model named, inside the element the model pointed at.

        The model points; it never reports. What it points at is usually a container — the
        reduced view offers a table by reference, not each of its cells — so taking the
        pointed element's text verbatim compares a whole infobox against one value and fails
        every time for the wrong reason. So the same binding rule the verifier uses is
        applied here, to the markup of that element as it was live.

        **This is weaker than the declared path and the difference is worth naming.** There,
        the executor reads through a scripted selector and the verifier re-resolves an
        independent anchor: two rules. Here it is one rule over two captures — the live
        fragment at the moment of the extract, and the stored artifact afterwards. It still
        catches a value that is not bound to its label, and a page that changed underneath
        the run. It would not catch the rule itself being wrong.
        """
        from app.verifier import AnchorAmbiguous, AnchorNotFound, _located_label

        ctx.candidate = {}
        names = [c["name"] for c in (ctx.run.postcondition or {}).get("claims", [])]
        names = names or ["answer"]
        # One reading per asked-for part, in the order the task asked (A25.3). The extracts
        # are walked forwards for the same reason: the model was told to emit them in that
        # order, and pairing the last extract with the first claim would bind a value to
        # the wrong question while every structural check still passed.
        readings: list[tuple[str, str]] = []
        for entry in ctx.run.trace:
            if entry.kind is not StepKind.EXTRACT or not entry.ok:
                continue
            anchor = str((entry.detail.get("args") or {}).get("label_anchor", "")).strip()
            fragment = str(entry.detail.get("fragment", ""))
            if not anchor or not fragment:
                continue
            spec = ClaimSpec(name="answer", label="", relation=Relation.LOCATED_LABEL,
                             value_type="string")
            try:
                value, _span, _path = _located_label(
                    lxml_html.fromstring(fragment), spec, {"answer_anchor": anchor})
            except (AnchorNotFound, AnchorAmbiguous, ValueError):
                continue
            readings.append((anchor, value))
        if len(names) == 1 and readings:
            # The single-claim case keeps taking the last usable extract: a run that
            # re-reads after a correction meant the later reading, and nothing about a
            # one-value task says the first attempt is the answer.
            anchor, value = readings[-1]
            ctx.candidate = {"answer": value, "answer_anchor": anchor}
            return
        for name, (anchor, value) in zip(names, readings):
            ctx.candidate[name] = value
            ctx.candidate[f"{name}_anchor"] = anchor
        return

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
        # Which Special: page the task actually asks for. Refusing a different URL than the
        # one requested would be correct about robots and wrong about the question, which is
        # the same defect as answering one.
        if re.search(r"search page|find articles|search for|wikipedia's search", low):
            # The opening quote must not be an apostrophe inside a word, or "Wikipedia's
            # search page ... 'convertible arbitrage'" yields everything after the `'` in
            # "Wikipedia's" as the search term.
            term = re.search(r"(?<!\w)[\"'\u2018\u201c]([^\"'\u2019\u201d]{3,})[\"'\u2019\u201d]",
                             low)
            page = "Search"
            target = (f"{WIKI_SPECIAL}Search?search="
                      f"{quote(term.group(1))}" if term else f"{WIKI_SPECIAL}Search")
            goal = ("Find Wikipedia articles matching a search term, which the site answers "
                    "at Special:Search.")
        else:
            page = "WhatLinksHere"
            target = f"{WIKI_SPECIAL}WhatLinksHere/{WIKI_SP500.rsplit('/', 1)[-1]}"
            goal = ("List the Wikipedia pages that link to the list of S&P 500 companies, "
                    "which the site answers at Special:WhatLinksHere.")
        pc = Postcondition(
            goal=goal,
            operation="OP-robots",
            target_url=target,
            inputs={"special_page": page},
            claims=(),
        )

        async def attempt(ctx: ExecutionContext) -> None:
            await self._navigate(ctx, target)

        return Plan("OP-robots", f"wikipedia Special:{page} (robots-Disallowed)",
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

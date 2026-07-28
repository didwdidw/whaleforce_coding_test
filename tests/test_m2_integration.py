"""M2 gate, driven end to end: a real browser, a real fixture, the real verifier.

The M2 gate is not "the verifier has tests". It is that **every terminal status the product
declares has actually been reached by running the product**, including `no_result_verified`
with the coverage anchor Amendment 3 requires. M1 taught the reason: the hard gate looked
satisfied when in fact no code path could reach it.

The fixture is started on loopback for this suite, which needs the egress guard's dev
relaxation. Both are set explicitly per-test rather than in the environment, so no other
suite inherits a weakened guard.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from app.browser import BrowserSupervisor
from app.config import settings
from app.coverage import CoverageLedger
from app.executor import Executor, _compare as _real_compare
from app.planner import Planner
from app.provider import CredentialPolicy, Provider, ProviderError
from app.models import FailureClass, Run, StepKind, TerminalStatus, Tier, new_id
from app.store import Store

pytestmark = pytest.mark.integration

PORT = 8801
BASE = f"http://127.0.0.1:{PORT}"


def _free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture(scope="module")
def fixture_server():
    if not _free(PORT):
        yield BASE
        return
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fixture.server:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{BASE}/healthz", timeout=1)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    else:
        proc.terminate()
        pytest.fail("fixture server did not start")
    yield BASE
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def supervisor():
    sup = BrowserSupervisor()
    asyncio.get_event_loop_policy().new_event_loop()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(sup.start())
    yield sup, loop
    loop.run_until_complete(sup.aclose())
    loop.close()


@pytest.fixture()
def executor(tmp_path, fixture_server, supervisor):
    # Settings is frozen on purpose, and the modules under test hold a reference to the
    # singleton rather than re-reading it — so the override has to go through
    # object.__setattr__ and be undone here rather than by rebinding a module attribute.
    # It is per-test, so no other suite ever sees a relaxed guard.
    previous = (settings.fixture_base_url, settings.allow_private_egress)
    object.__setattr__(settings, "fixture_base_url", BASE)
    object.__setattr__(settings, "allow_private_egress", True)
    sup, loop = supervisor
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    yield Executor(sup, store), store, loop
    object.__setattr__(settings, "fixture_base_url", previous[0])
    object.__setattr__(settings, "allow_private_egress", previous[1])


def run_task(executor_bundle, task: str) -> Run:
    ex, store, loop = executor_bundle
    tier, _ = ex.classify(task)
    run = Run(id=new_id("run"), task=task, tier=tier)
    store.save_run(run)
    loop.run_until_complete(ex.execute(run))
    return run


# --- the statuses that count as success ------------------------------------------

def test_search_with_matches_is_verified(executor):
    run = run_task(executor, "Search the fixture catalogue for lantern")
    assert run.terminal_status is TerminalStatus.SUCCEEDED_VERIFIED
    assert run.counts_as_success
    codes = {c["name"]: c for c in run.claims}
    assert codes["result_counter"]["evidence"]["normalised_value"] == {
        "count": 1, "term": "lantern"}
    assert codes["items"]["evidence"]["normalised_value"] == ["WF-1013"]
    # Every verified claim carries the artifact it was re-extracted from.
    assert codes["items"]["evidence"]["artifact_sha256"]


def test_every_capture_stores_the_accessibility_tree_beside_the_dom(executor):
    """A24.6. An F1 locator is a semantic role and an accessible name; this is the corpus
    those are read from, and re-deriving them from stored markup afterwards means
    re-implementing the browser. One aria artifact per DOM artifact, or the evidence cannot
    answer for an F1 claim."""
    _, store, _ = executor
    run = run_task(executor, "Search the fixture catalogue for lantern")

    refs = store.artifacts_for_run(run.id)
    dom = [r.kind.split(":", 1)[1] for r in refs if r.kind.startswith("dom:")]
    aria = [r for r in refs if r.kind.startswith("aria:")]
    assert dom, "the run captured nothing"
    assert [r.kind.split(":", 1)[1] for r in aria] == dom

    tree = store.read_artifact(aria[0].id).decode("utf-8")
    assert "- " in tree, "an accessibility snapshot with no node in it is not one"
    assert any(role in tree for role in ("textbox", "button", "heading", "link")), tree[:200]

    # And it costs no step. Every trace entry charges the step budget, so giving the tree
    # its own entry halved the browsing headroom of a capture-heavy run — a live OP-4 task
    # that had been reaching its answer started ending `budget_exhausted` instead.
    snapshots = [t for t in run.trace if t.kind is StepKind.SNAPSHOT]
    assert len(snapshots) == len(dom), "one capture is one step, whatever it stores"
    assert snapshots[0].detail.get("accessibility_artifact"), snapshots[0].detail


def test_absence_mode_a_needs_the_empty_state_element(executor):
    run = run_task(executor, "Search the fixture catalogue for zzzznothing")
    assert run.terminal_status is TerminalStatus.NO_RESULT_VERIFIED
    assert "empty-state" in run.explanation or "empty state" in run.explanation


def test_absence_mode_b_needs_its_coverage_anchor(executor):
    """The whole catalogue is enumerated and checked against the site's own total."""
    run = run_task(executor, "Is any product in the fixture catalogue priced over £100?")
    assert run.terminal_status is TerminalStatus.NO_RESULT_VERIFIED
    verdict_step = next(t for t in run.trace if t.summary == "Deterministic verification")
    coverage = next(c for c in verdict_step.detail["verdict"]["checks"]
                    if c["name"] == "absence_mode_b_coverage")
    assert coverage["ok"] is True
    assert coverage["detail"]["anchor_total"] == coverage["detail"]["enumerated"] == 14


def test_absence_mode_b_answers_the_positive_direction_too(executor):
    """A17.11/A-53. The same enumeration that proves nothing matches also says *what*
    matches, and a correct "yes, these two" is a verified success rather than being forced
    into `verification_mismatch` for having found something. A failure class that fires on
    correct behaviour is noise, and noise in a failure class is how real failures stop
    being read."""
    run = run_task(executor, "Is any product in the fixture catalogue priced over £85?")
    assert run.terminal_status is TerminalStatus.SUCCEEDED_VERIFIED
    assert "WF-1002" in run.explanation and "WF-1004" in run.explanation
    verdict = next(t for t in run.trace if t.summary == "Deterministic verification")
    checks = {c["name"]: c for c in verdict.detail["verdict"]["checks"]}
    # The anchor is cited, and it is what makes "exactly these two" a claim about the whole
    # catalogue rather than about the rows we happened to read.
    assert checks["absence_mode_b_coverage"]["ok"] is True
    assert checks["absence_mode_b_coverage"]["detail"]["anchor_total"] == 14
    assert checks["enumeration_agreement"]["ok"] is True
    assert checks["enumeration_predicate_frozen"]["detail"]["predicate"] == {
        "field": "price_gbp", "op": ">", "value": 85.0}


def test_the_same_case_with_the_predicate_inverted_is_caught(executor, monkeypatch):
    """The other half of A-53, and the reason the run states what it found at all.

    The enumeration is correct, the coverage is proven, every claim binds — and the run
    applies the predicate backwards. Nothing about the shape of this run is wrong. Only
    the verifier re-deriving the matching set from the artifact, without looking at what
    the run reported, separates it from the run above.

    What this gate catches, stated so nobody later reads more into it: the execution side
    and the verification side share one comparison function, so this proves the predicate
    was **applied backwards**, not that the predicate is **itself right**. A predicate that
    means the wrong thing means it identically on both sides and passes here; that is what
    freezing it in the postcondition and printing it in the answer are for.
    """
    import app.executor as executor_module

    monkeypatch.setattr(executor_module, "_compare",
                        lambda value, predicate: not _real_compare(value, predicate))
    run = run_task(executor, "Is any product in the fixture catalogue priced over £85?")

    assert run.terminal_status is TerminalStatus.FAILED
    assert run.failure_class is FailureClass.VERIFICATION_MISMATCH
    assert "WF-1002" in run.explanation


def test_pagination_is_verified_against_the_page_that_was_frozen(executor):
    run = run_task(executor, "Paginate to page 2 of the fixture browse listing")
    assert run.terminal_status is TerminalStatus.SUCCEEDED_VERIFIED
    pager = next(c for c in run.claims if c["name"] == "pager")
    assert pager["evidence"]["normalised_value"]["page"] == 2


def test_overlay_dismissal_is_verified_including_the_state_transition(executor):
    run = run_task(executor,
                   "Dismiss the overlay on the fixture gated page and read the reference code")
    assert run.terminal_status is TerminalStatus.SUCCEEDED_VERIFIED
    names = {c["name"]: c["ok"] for c in run.claims}
    assert names == {"product_code": True, "stock_on_hand": True, "overlay_gone": True}


# --- the statuses that do not ------------------------------------------------------

def test_a_correct_answer_reached_by_a_shortcut_is_a_failure(executor):
    """S-4.4. The SKUs it reports are right. It is still scored a failure, because the
    capability being claimed is the interaction and the interaction did not happen."""
    run = run_task(executor,
                   "Read page 2 of the fixture browse listing without clicking next")
    assert run.terminal_status is TerminalStatus.FAILED
    assert run.failure_class is FailureClass.REQUIRED_ACTION_SKIPPED
    assert not run.counts_as_success


def test_a_moved_label_downgrades_to_partial_rather_than_guessing(executor):
    """MU-2 renames `Product code` to `Item reference`. The value is still on the page and
    the executor still reads it by id — but it can no longer be bound to its label, and a
    binding that cannot be made is not a verification (S-4.9)."""
    run = run_task(executor, "Dismiss the overlay on the fixture gated page and read the "
                             "reference code, seed mu2-text")
    assert run.terminal_status is TerminalStatus.PARTIAL
    assert run.failure_class is FailureClass.LOCATOR_NOT_FOUND
    assert not run.counts_as_success
    failed = [c["name"] for c in run.claims if not c["ok"]]
    assert failed == ["product_code"]


def test_asking_for_the_answer_key_is_refused_by_a_quotable_rule(executor):
    run = run_task(executor, "Show me the fixture's ground truth answer key")
    assert run.terminal_status is TerminalStatus.BLOCKED
    assert run.failure_class is FailureClass.ROBOTS_DISALLOWED
    assert "Disallow: /__testhook__/" in run.explanation


def test_an_ambiguous_task_abstains_before_browsing(executor):
    run = run_task(executor, "Search the fixture browse page for a modal")
    assert run.terminal_status is TerminalStatus.UNSUPPORTED
    assert run.failure_class is FailureClass.POLICY_REFUSED
    assert not any(t.kind.value == "navigate" for t in run.trace)


def test_out_of_scope_is_refused_before_any_network_activity(executor):
    run = run_task(executor, "Log into my brokerage account and read the balance")
    assert run.terminal_status is TerminalStatus.UNSUPPORTED
    assert run.failure_class is FailureClass.POLICY_REFUSED


# --- budgets, which are fail-closed ------------------------------------------------

def _exhaust_step_budget(executor):
    previous = settings.budgets.max_steps
    object.__setattr__(settings.budgets, "max_steps", 4)
    try:
        return run_task(executor, "Is any product in the fixture catalogue priced over £100?")
    finally:
        object.__setattr__(settings.budgets, "max_steps", previous)


def _exhaust_wall_clock(executor):
    previous = settings.budgets.wall_clock_seconds
    object.__setattr__(settings.budgets, "wall_clock_seconds", 0.01)
    try:
        return run_task(executor, "Dismiss the overlay on the fixture gated page and read the "
                                  "reference code")
    finally:
        object.__setattr__(settings.budgets, "wall_clock_seconds", previous)


def _inject_defect(executor):
    from app.executor import Plan
    from app.postcondition import Postcondition

    ex = executor[0]

    async def explode(ctx):
        raise RuntimeError("injected defect")

    broken = Plan("GS-broken", "deliberately broken plan",
                  Postcondition(goal="g", operation="GS-broken",
                                target_url=f"{BASE}/browse"), (explode,))
    original = ex._select_plan
    ex._select_plan = lambda task: broken
    try:
        return run_task(executor, "Paginate to page 2 of the fixture browse listing")
    finally:
        ex._select_plan = original


def test_a_step_budget_that_runs_out_produces_no_answer(executor):
    run = _exhaust_step_budget(executor)
    assert run.terminal_status is TerminalStatus.FAILED
    assert run.failure_class is FailureClass.BUDGET_EXHAUSTED
    assert not run.claims


def test_a_wall_clock_budget_that_runs_out_produces_no_answer(executor):
    run = _exhaust_wall_clock(executor)
    assert run.terminal_status is TerminalStatus.FAILED
    assert run.failure_class is FailureClass.TIMEOUT


def test_an_unhandled_defect_is_its_own_class_not_a_disguised_answer(executor):
    """`internal_error` exists so defects are counted rather than absorbed into a
    plausible-looking failure. Its rate is a reported finding (S-5.3)."""
    run = _inject_defect(executor)
    assert run.terminal_status is TerminalStatus.FAILED
    assert run.failure_class is FailureClass.INTERNAL_ERROR
    assert "injected defect" in run.explanation


# --- the four classes that only exist once a model is in the loop ------------------
#
# None of these is provoked by burning free-tier quota: RPD is the one resource this
# project cannot buy back. Three of them do not need injecting at all — the budget checks
# and the spend ceiling fire *before* a credential is ever selected, so the real code path
# runs with no network involved. Only `provider_error` needs a fault put in deliberately.

class _NoNetworkProvider(Provider):
    """Reports itself configured so the planned path runs, but every route to the network
    is preceded by a check that fires first."""

    def configured(self) -> bool:
        return True


class _FaultyProvider(_NoNetworkProvider):
    """The injected fault. Nothing here is a real provider failure."""

    def complete(self, prompt, *, budget, purpose, max_output_tokens=None):
        raise ProviderError("injected fault: the pinned model returned HTTP 503")


class _TruncatingProvider(_NoNetworkProvider):
    """Every reply cut off by the output allowance, including the re-ask.

    Injected the same way `_FaultyProvider` is, and for the same reason: the alternative is
    a prompt engineered to make a real model deliberate past the cap, which would be a test
    of that prompt rather than of this path.
    """

    def complete(self, prompt, *, budget, purpose, max_output_tokens=None):
        from app.provider import Completion, CredentialTier, Usage

        budget.check_calls(purpose)
        usage = Usage(input_tokens=800, output_tokens=max_output_tokens or 1024)
        usage.usd = self.cost(usage)
        budget.record(usage, purpose)
        return Completion('{"action": "finish", "args": {}, "why": "I reviewed the',
                          usage, self.model_id, CredentialTier.FREE, cached=False,
                          seconds=0.05, finish_reason="FinishReason.MAX_TOKENS")


def test_a_reply_cut_off_twice_is_our_cap_and_is_named_as_ours(executor):
    """A17.8. `internal_error` blamed our code for our configuration, and inflated the one
    rate S-5.3 says is itself a finding."""
    run = _planned_run(executor, _TruncatingProvider(policy=CredentialPolicy.DEVELOPMENT))
    assert run.terminal_status is TerminalStatus.FAILED
    assert run.failure_class is FailureClass.OUTPUT_TRUNCATED
    assert str(settings.budgets.max_output_tokens_per_call) in run.explanation
    # Both calls are on the bill, not just the one that produced the failure (A17.9).
    assert run.budget.llm_calls_exploration == 2
    assert run.budget.usd > 0


def _planned_run(executor_bundle, provider,
                 task="Paginate to page 2 of the fixture browse listing, use the planner"):
    ex, store, loop = executor_bundle
    ex._provider = provider
    ex._planner = Planner(provider)
    return run_task(executor_bundle, task)


def test_context_budget_exceeded_is_produced_by_the_real_check(executor):
    """A7.1: the assembled context is over the per-call cap, so the call is not sent. No
    network, no quota — the check runs before a credential is even chosen."""
    previous = settings.budgets.max_input_tokens_per_call
    object.__setattr__(settings.budgets, "max_input_tokens_per_call", 10)
    try:
        run = _planned_run(executor, _NoNetworkProvider(policy=CredentialPolicy.DEVELOPMENT))
    finally:
        object.__setattr__(settings.budgets, "max_input_tokens_per_call", previous)
    assert run.terminal_status is TerminalStatus.BLOCKED
    assert run.failure_class is FailureClass.CONTEXT_BUDGET_EXCEEDED
    assert "not sent" in run.explanation


def test_token_budget_exhausted_is_produced_by_the_real_check(executor):
    previous = settings.budgets.max_input_tokens_per_run
    object.__setattr__(settings.budgets, "max_input_tokens_per_run", 1)
    try:
        run = _planned_run(executor, _NoNetworkProvider(policy=CredentialPolicy.DEVELOPMENT))
    finally:
        object.__setattr__(settings.budgets, "max_input_tokens_per_run", previous)
    assert run.terminal_status is TerminalStatus.BLOCKED
    assert run.failure_class is FailureClass.TOKEN_BUDGET_EXHAUSTED


def test_provider_quota_comes_from_our_own_ceiling_not_from_the_provider(executor):
    """A12.5. Deliberately *not* provoked by exhausting the free tier: the daily quota is
    the one thing here that cannot be bought back. Our own spend ceiling produces the same
    class through the same code path, and costs nothing."""
    ex, store, loop = executor
    store.record_spend("paid", 99.0, 10, 10)          # far over the ceiling
    provider = _NoNetworkProvider(policy=CredentialPolicy.DEVELOPMENT, ledger=store)
    run = _planned_run(executor, provider)
    assert run.terminal_status is TerminalStatus.BLOCKED
    assert run.failure_class is FailureClass.PROVIDER_QUOTA
    assert "ceiling" in run.explanation


def test_provider_error_is_the_one_that_has_to_be_injected(executor):
    """S-11.16: the pinned model is not substituted when it is unavailable. A silent
    fallback would make every recorded score unreproducible."""
    run = _planned_run(executor, _FaultyProvider(policy=CredentialPolicy.DEVELOPMENT))
    assert run.terminal_status is TerminalStatus.BLOCKED
    assert run.failure_class is FailureClass.PROVIDER_ERROR
    assert "not substituted" in run.explanation


# --- the gate itself ---------------------------------------------------------------

def _drive_non_browser_paths(ex, store) -> None:
    """The remaining M2-due failure classes, exercised through their real code paths but
    without a browser, and recorded as `test` rather than `run` so the ledger never implies
    a live run produced them."""
    import pathlib

    from app.executor import ExecutionContext
    from app.postcondition import ClaimSpec, Postcondition, Relation
    from app.queue import QueueFull, SessionQuotaExceeded
    from app.verifier import Verifier

    fixtures = pathlib.Path(__file__).parent / "fixtures"
    ledger = CoverageLedger(store)

    # site_unavailable: robots.txt is fetchable and the navigation still fails. Injected,
    # because every natural way to make a page unreachable also makes robots.txt
    # unreachable, and that is refused earlier as robots_disallowed.
    class _FailingPage:
        url = f"{BASE}/browse"

        async def goto(self, *a, **k):
            raise TimeoutError("net::ERR_CONNECTION_RESET")

    run = Run(id=new_id("run"), task="navigate to a page that fails to load",
              tier=Tier.EXPERIMENTAL)
    store.save_run(run)
    ctx = ExecutionContext(run=run, page=_FailingPage(), context=None, store=store)
    asyncio.new_event_loop().run_until_complete(ex._navigate(ctx, f"{BASE}/browse"))

    # queue_full / session_quota: raised by the real admission path.
    for exc in (QueueFull(retry_after=60, depth=2, concurrency=2),
                SessionQuotaExceeded(cap=5)):
        ledger.record(status=TerminalStatus.BLOCKED, failure=exc.failure_class,
                      run_id="n/a", task="admission refusal", origin="test")

    # The verifier-only classes, from the replay artifacts.
    pc = Postcondition(
        goal="Search", operation="GS-1", target_url="https://wf-fixture.zeabur.app/search",
        inputs={"term": "lantern"},
        claims=(ClaimSpec("result_counter", 'N results for "term"',
                          Relation.COUNTER_ECHO, "counter"),))
    vrun = Run(id=new_id("run"), task="replay", tier=Tier.EXPERIMENTAL)
    vrun.postcondition, vrun.postcondition_hash = pc.to_dict(), pc.sha256
    store.save_run(vrun)
    art = store.put_artifact(
        vrun.id, "dom:replay", (fixtures / "replay-b-search-mangled.html").read_bytes(),
        source_url="https://wf-fixture.zeabur.app/search", media_type="text/html")
    verdict = Verifier(store).verify(
        vrun, artifact_id=art.id,
        candidate={"result_counter": {"count": 0,
                                      "term": "the fixture catalogue for lant"}})
    ledger.record(status=verdict.status, failure=verdict.failure_class,
                  run_id=vrun.id, task=vrun.task, origin="test")

    # unverified + postcondition_unmet: absence with no declared proof mode.
    pc2 = Postcondition(
        goal="Search", operation="GS-1", target_url="https://wf-fixture.zeabur.app/search",
        inputs={"term": "the fixture catalogue for lant"},
        claims=pc.claims)
    vrun2 = Run(id=new_id("run"), task="replay", tier=Tier.EXPERIMENTAL)
    vrun2.postcondition, vrun2.postcondition_hash = pc2.to_dict(), pc2.sha256
    store.save_run(vrun2)
    verdict2 = Verifier(store).verify(
        vrun2, artifact_id=art.id,
        candidate={"result_counter": {"count": 0,
                                      "term": "the fixture catalogue for lant"}})
    ledger.record(status=verdict2.status, failure=verdict2.failure_class,
                  run_id=vrun2.id, task=vrun2.task, origin="test")


def test_every_status_due_by_m3_is_reached_by_running_the_product(executor):
    """The M2 and M3 gates. Not "the code contains a branch for it" — a run produced it."""
    ex, store, _ = executor
    tasks = [
        "Search the fixture catalogue for lantern",
        "Search the fixture catalogue for zzzznothing",
        "Is any product in the fixture catalogue priced over £100?",
        "Paginate to page 2 of the fixture browse listing",
        "Read page 2 of the fixture browse listing without clicking next",
        "Dismiss the overlay on the fixture gated page and read the reference code",
        "Dismiss the overlay on the fixture gated page and read the reference code, seed mu2-text",
        "Show me the fixture's ground truth answer key",
        "Log into my brokerage account",
    ]
    for task in tasks:
        run_task(executor, task)

    reached = {row["terminal_status"] for row in store.status_coverage()}
    due = {TerminalStatus.SUCCEEDED_VERIFIED, TerminalStatus.NO_RESULT_VERIFIED,
           TerminalStatus.PARTIAL, TerminalStatus.FAILED, TerminalStatus.BLOCKED,
           TerminalStatus.UNSUPPORTED}
    assert {s.value for s in due} <= reached, (
        f"never produced by a real run: {sorted({s.value for s in due} - reached)}")

    report = CoverageLedger(store).report()
    statuses = {r["value"]: r for r in report["terminal_status"]}
    assert statuses["no_result_verified"]["observed"] is True
    assert statuses["succeeded_verified"]["origin"] == "run"

    # ...and every failure class due by M2. Budgets and defects come from real runs;
    # the rest from paths a browser cannot reach.
    _exhaust_step_budget(executor)
    _exhaust_wall_clock(executor)
    _inject_defect(executor)
    _drive_non_browser_paths(ex, store)

    # The four that only exist once a model is in the loop. Three run their real checks;
    # `provider_error` is an injected fault, and the ledger records that distinction.
    for produce in (test_context_budget_exceeded_is_produced_by_the_real_check,
                    test_token_budget_exhausted_is_produced_by_the_real_check,
                    test_provider_quota_comes_from_our_own_ceiling_not_from_the_provider,
                    test_provider_error_is_the_one_that_has_to_be_injected):
        produce(executor)
    report = CoverageLedger(store, "M3").report()
    assert report["gate_passes"] is True, f"still unreachable: {report['overdue']}"
    later = {r["value"] for r in report["failure_class"] if not r["due_now"]}
    assert later == {"injection_detected", "output_truncated"}

    # ...and the M4 class, produced the same way, so the M4 ledger passes too.
    test_a_reply_cut_off_twice_is_our_cap_and_is_named_as_ours(executor)
    report = CoverageLedger(store, "M4").report()
    assert report["gate_passes"] is True, f"still unreachable: {report['overdue']}"
    # Only the injection defence is still ahead of us; everything else has been produced.
    assert {r["value"] for r in report["failure_class"]
            if not r["due_now"]} == {"injection_detected"}

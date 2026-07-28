"""The planner's contract, and the budgets that bound it. No network.

The model is a proposer. Everything it returns is validated before it can reach a browser,
and the interesting cases are the ones where a plausible-looking proposal is refused: an
action outside the allow-list, a ref we never offered, an invented diagnosis, a coordinate
click. A proposal that fails validation is recorded and refused — never repaired into
something that looks acceptable.
"""

from __future__ import annotations

import json

import pytest

from app.config import settings
from app.models import DiagnosedCause, StrategyFamily
from app.planner import ProposalRejected, parse_proposal, validate
from app.provider import (
    ContextBudgetExceeded, CredentialPolicy, CredentialTier, Provider, RunBudget,
    TokenBudgetExhausted, _classify, estimate_tokens,
)

VIEW = {
    "rule_version": "reduce/v1.1",
    "interactive": [
        {"ref": "e1", "role": "input", "name": "Product name or code", "value": ""},
        {"ref": "e2", "role": "button", "name": "Search"},
    ],
    "anchor_regions": [{"ref": "e9", "tag": "table", "rows": [["Note 4471", "text"]]}],
}


def _proposal(**over):
    body = {"action": "click", "args": {"ref": "e2"}, "why": "submit the form",
            "strategy": "F1", "diagnosis": "none"}
    body.update(over)
    return parse_proposal(json.dumps(body))


# --- parsing ----------------------------------------------------------------------

def test_a_well_formed_proposal_parses_into_named_types():
    p = _proposal()
    assert p.action == "click"
    assert p.strategy is StrategyFamily.F1_SEMANTIC
    assert p.diagnosis is DiagnosedCause.NONE


def test_a_fenced_json_block_is_accepted():
    """Failing on a markdown wrapper would report a model error where there is a wrapper."""
    p = parse_proposal('```json\n{"action":"finish","args":{},"diagnosis":"none"}\n```')
    assert p.action == "finish"


@pytest.mark.parametrize("text", ["", "not json at all", "[1,2,3]"])
def test_unparseable_responses_are_rejected_not_guessed(text):
    with pytest.raises(ProposalRejected):
        parse_proposal(text)


def test_an_invented_diagnosis_is_refused():
    """S-7.6: a cause that is not in the closed set cannot be counted or compared, and
    "it threw an exception" is not a diagnosis."""
    with pytest.raises(ProposalRejected) as exc:
        _proposal(diagnosis="the button was weird")
    assert "named causes" in exc.value.reason


# --- validation -------------------------------------------------------------------

def test_an_action_outside_the_allow_list_is_refused():
    with pytest.raises(ProposalRejected) as exc:
        validate(_proposal(action="execute_script", args={"code": "alert(1)"}), VIEW)
    assert "allow-list" in exc.value.reason


def test_a_ref_we_never_offered_is_refused():
    """Acting on a ref that was not in the view means acting on something invented."""
    with pytest.raises(ProposalRejected) as exc:
        validate(_proposal(args={"ref": "e999"}), VIEW)
    assert "not in the view" in exc.value.reason


def test_an_anchor_region_is_a_legitimate_extraction_target():
    """`extract` names a container plus the label the value is bound to — the same shape
    the verifier uses. An earlier version of this check knew only about interactive
    elements and rejected a correct proposal."""
    validate(_proposal(action="extract",
                       args={"ref": "e9", "label_anchor": "Note 4471"}), VIEW)


def test_missing_required_arguments_are_refused():
    with pytest.raises(ProposalRejected) as exc:
        validate(_proposal(action="fill", args={"ref": "e1"}), VIEW)
    assert "requires" in exc.value.reason


def test_coordinate_clicking_is_refused_at_the_boundary():
    """S-7.3: blind clicking is prohibited, so it is refused before it is attempted rather
    than attempted and then judged."""
    with pytest.raises(ProposalRejected) as exc:
        validate(_proposal(strategy="F4"), VIEW)
    assert "abstain" in exc.value.reason


# --- budgets ----------------------------------------------------------------------

def test_exploration_cannot_eat_the_recovery_reserve():
    """A run that spends its recovery budget on exploration dies before it can demonstrate
    the self-correction it is being graded on."""
    budget = RunBudget(exploration_calls=settings.budgets.exploration_calls)
    with pytest.raises(Exception) as exc:
        budget.check_calls("exploration")
    assert "recovery reserve" in str(exc.value)
    budget.check_calls("recovery")          # still available, by design


def test_recovery_budget_is_bounded_too():
    budget = RunBudget(recovery_calls=settings.budgets.recovery_calls)
    with pytest.raises(Exception):
        budget.check_calls("recovery")


def test_an_oversized_context_is_not_sent():
    """A7.1: the call fails closed rather than being trimmed silently or sent anyway."""
    with pytest.raises(ContextBudgetExceeded) as exc:
        RunBudget().check_tokens(settings.budgets.max_input_tokens_per_call + 1)
    assert "not sent" in str(exc.value)


def test_the_run_token_budget_is_cumulative():
    budget = RunBudget(input_tokens=settings.budgets.max_input_tokens_per_run - 10)
    with pytest.raises(TokenBudgetExhausted):
        budget.check_tokens(100)


def test_the_output_budget_is_enforced_because_output_is_the_expensive_half():
    budget = RunBudget(output_tokens=settings.budgets.max_output_tokens_per_run)
    with pytest.raises(TokenBudgetExhausted) as exc:
        budget.check_tokens(10)
    assert "dominant cost" in str(exc.value)


def test_token_estimation_errs_high_rather_than_low():
    """The estimate decides whether a call may be sent at all, so it must not undercount:
    asking the provider how big a prompt is means sending it."""
    assert estimate_tokens("x" * 3000) >= 3000 // 4


# --- credentials ------------------------------------------------------------------

def test_the_public_demo_never_falls_back_to_billed_credentials():
    """A visitor's run must not spend billed quota; exhaustion is reported honestly."""
    p = Provider(policy=CredentialPolicy.PUBLIC_DEMO)
    assert p.available_tiers() == [CredentialTier.FREE]


def test_a_scored_run_starts_on_the_paid_key_unconditionally():
    """A9.6: a held-out split cannot be re-run, so it must not be able to die of free-tier
    exhaustion halfway through."""
    p = Provider(policy=CredentialPolicy.SCORED)
    assert p.available_tiers() == [CredentialTier.PAID]


def test_development_falls_back_free_then_paid():
    p = Provider(policy=CredentialPolicy.DEVELOPMENT)
    assert p.available_tiers() == [CredentialTier.FREE, CredentialTier.PAID]


def test_a_moving_model_alias_is_refused_at_startup():
    """S-11.15: `latest` and preview ids change under us, which makes every recorded score
    unreproducible."""
    for bad in ("gemini-flash-latest", "gemini-3.0-pro-preview", "gemini-exp-1206"):
        with pytest.raises(SystemExit) as exc:
            Provider(model_id=bad).validate_or_die()
        assert "pinned stable id" in str(exc.value)


def test_quota_errors_are_told_apart_from_faults():
    """They mean different things to a run: a resource limit versus a defect."""
    from app.models import FailureClass

    quota = _classify(RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"))
    fault = _classify(RuntimeError("500 INTERNAL: something broke"))
    assert quota.failure_class is FailureClass.PROVIDER_QUOTA
    assert fault.failure_class is FailureClass.PROVIDER_ERROR


def test_keys_are_never_read_from_the_environment():
    """An environment dump would put a key in a trace, a log line or a prompt record.

    Checked by parsing rather than grepping: the module's own docstring explains the rule,
    and a text search flags the explanation. That mistake has been made once already, in the
    check that `urllib.robotparser` stays banned.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("app/provider.py").read_text(encoding="utf-8"))
    reads = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            reads.append(node.attr)
        if isinstance(node, ast.Name) and node.id in ("environ", "getenv"):
            reads.append(node.id)
    assert not reads, f"the provider adapter reads the environment: {reads}"


# --- A12.5 / A-33: the spend ceiling refuses before the call ----------------------

def test_the_spend_ceiling_refuses_before_the_call_not_after(tmp_path, monkeypatch):
    """A8.10's limit existed as a number in someone's head while the paid key was already
    in use. A ceiling checked after the call is a report, not a control."""
    from app.models import FailureClass
    from app.provider import ProviderQuotaExhausted
    from app.store import Store

    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    store.record_spend("paid", 9.0, 1000, 100)          # over the USD 8 cumulative ceiling

    provider = Provider(policy=CredentialPolicy.DEVELOPMENT, ledger=store)
    with pytest.raises(ProviderQuotaExhausted) as exc:
        provider.complete("anything", budget=RunBudget(), purpose="exploration")

    assert exc.value.failure_class is FailureClass.PROVIDER_QUOTA
    assert "cumulative billed spend ceiling" in str(exc.value)
    # ...and the state that decided it survives a restart, because it is on disk.
    assert Store(tmp_path / "runs.sqlite3",
                 tmp_path / "artifacts").spend()["cumulative_billed_usd"] == 9.0


def test_the_daily_ceiling_is_separate_from_the_cumulative_one(tmp_path, monkeypatch):
    from app.provider import ProviderQuotaExhausted
    from app.store import Store

    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    store.record_spend("paid", 3.0, 1000, 100)      # under the USD 8 total, over the daily

    provider = Provider(policy=CredentialPolicy.DEVELOPMENT, ledger=store)
    with pytest.raises(ProviderQuotaExhausted) as exc:
        provider.complete("anything", budget=RunBudget(), purpose="exploration")
    assert "Today's billed spend ceiling" in str(exc.value)


# --- A23.1 / A-68: the ceiling measures money, and free-tier calls are not money ------

def test_free_tier_calls_do_not_consume_the_billed_ceiling(tmp_path, monkeypatch):
    """The ledger priced free-tier calls and the gate checked the priced total, so the
    public demo was on course to refuse work as `provider_quota` having spent nothing —
    a terminal status that looks entirely normal and describes an event that did not
    happen."""
    from app.store import Store

    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    store.record_spend("free", 40.0, 100000, 10000)     # far over every ceiling, in cost

    spend = store.spend()
    assert spend["cumulative_billed_usd"] == 0.0        # because none of it was charged
    assert spend["cumulative_notional_usd"] == 40.0     # and it is still on the record

    provider = Provider(policy=CredentialPolicy.PUBLIC_DEMO, ledger=store)
    # No refusal: nothing has been spent. The call fails for want of a key in this
    # environment, which is a different sentence from "the ceiling has been reached".
    provider._check_spend()


def test_the_public_path_may_not_spend_billed_money_before_the_a15_switchover():
    """A23.4 leaves the public cumulative allowance to be decided at the switchover. Until
    it is decided the answer is zero, not the development budget — grader traffic is
    outside this budget and must not be able to consume it."""
    from app.config import cumulative_ceiling_usd

    assert cumulative_ceiling_usd("public_demo") == 0.0
    assert cumulative_ceiling_usd("scored") == cumulative_ceiling_usd("development") == 8.0


def test_a_paid_credential_reachable_from_the_public_policy_is_refused(tmp_path,
                                                                      monkeypatch):
    """Defence in depth for A12.2. The topology should make this impossible; if it ever
    stops being impossible, the refusal is cheaper than the invoice."""
    from app.provider import CredentialTier, ProviderQuotaExhausted
    from app.store import Store

    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    provider = Provider(policy=CredentialPolicy.PUBLIC_DEMO, ledger=store)
    monkeypatch.setattr(provider, "available_tiers",
                        lambda: [CredentialTier.FREE, CredentialTier.PAID])
    with pytest.raises(ProviderQuotaExhausted) as exc:
        provider._check_spend()
    assert "no authorised cumulative spend" in str(exc.value)


def test_what_still_bounds_the_public_path_once_the_usd_gate_stops_binding(tmp_path,
                                                                          monkeypatch):
    """A23.2's third condition. The USD ceiling was accidentally acting as a request
    limiter for a path that spends nothing; removing that is only safe if the bounds that
    were supposed to be doing the work are actually there. Removing one gate without
    confirming the rest is A21.5's defect pointed the other way, so this asserts each of
    the three by exercising it rather than by reading the configuration.
    """
    from app.models import FailureClass
    from app.provider import ProviderQuotaExhausted
    from app.store import Store

    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")

    # 1. The free tier's own limit still ends a run honestly (A15.2). Raised from the
    #    adapter's own classifier, so a provider 429 cannot arrive as anything else.
    exhausted = _classify(RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"))
    assert isinstance(exhausted, ProviderQuotaExhausted)
    assert exhausted.failure_class is FailureClass.PROVIDER_QUOTA

    provider = Provider(policy=CredentialPolicy.PUBLIC_DEMO, ledger=store)
    monkeypatch.setattr(provider, "key_for", lambda tier: "k")
    monkeypatch.setattr(provider, "_call",
                        lambda *a, **k: (_ for _ in ()).throw(exhausted))
    with pytest.raises(ProviderQuotaExhausted) as refused:
        provider.complete("anything", budget=RunBudget(), purpose="exploration")
    assert "does not fall back to billed credentials" in str(refused.value)

    # 2 and 3. The session cap and the queue depth, which are what actually bound how much
    #    work one visitor and all visitors can ask for (S-11.8, S-11.12).
    assert settings.queue.session_run_cap > 0
    assert settings.queue.depth > 0 and settings.queue.concurrency > 0


def test_the_health_endpoint_says_which_dollars_are_money(tmp_path, monkeypatch):
    """A23.2: both figures are reported and each says which it is. One key meaning either
    kind of dollar is what let the gate measure something it was not measuring."""
    from app.store import Store

    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    store.record_spend("free", 0.5, 1000, 100)
    store.record_spend("paid", 0.25, 1000, 100)

    state = Provider(policy=CredentialPolicy.SCORED, ledger=store).spend_state()
    assert state["today_billed_usd"] == 0.25
    assert state["today_notional_usd"] == 0.5
    assert state["enforced_against"] == "billed"
    assert "money" in state["meaning"]["billed"]
    assert "not charged" in state["meaning"]["notional"]
    # No combined total: a reader cannot mistake one kind of dollar for the other if the
    # sum of the two is not offered as a number.
    assert "today_usd" not in state and "cumulative_usd" not in state


# --- a cut-off reply is not a broken contract (A14.8's DEV-11 entry) -----------------

def test_a_reply_cut_off_by_the_output_allowance_is_retried_once_then_named():
    """The per-call output allowance is shared with the model's thinking tokens, so a long
    deliberation can leave too few for the JSON to close. Reported as `internal_error` that
    accused our own code of a defect it did not have."""
    from app.planner import Planner, ResponseTruncated
    from app.provider import Completion, CredentialTier, RunBudget, Usage

    cut_off = Completion('{"action": "finish", "args": {}, "why": "I reviewed the',
                         Usage(), "m", CredentialTier.FREE, cached=False, seconds=0.1,
                         finish_reason="FinishReason.MAX_TOKENS")

    class _Provider:
        calls = 0

        def complete(self, prompt, **kwargs):
            type(self).calls += 1
            return cut_off

    planner = Planner(provider=_Provider())
    with pytest.raises(ResponseTruncated):
        planner.propose("p", budget=RunBudget(), purpose="exploration", view={})
    assert _Provider.calls == 2, "the second attempt must actually be made"


def test_the_retry_succeeds_and_is_recorded_as_having_happened():
    """A run that quietly made two calls for one step has a cost and a call count nobody
    can explain from the trace."""
    from app.planner import Planner
    from app.provider import Completion, CredentialTier, RunBudget, Usage

    replies = iter([
        Completion('{"action": "finish", "args": {}, "why": "I reviewed the',
                   Usage(), "m", CredentialTier.FREE, cached=False, seconds=0.1,
                   finish_reason="FinishReason.MAX_TOKENS"),
        Completion('{"action": "finish", "args": {}, "why": "done", "strategy": "F1",'
                   ' "diagnosis": "none"}',
                   Usage(), "m", CredentialTier.FREE, cached=False, seconds=0.1,
                   finish_reason="STOP"),
    ])

    class _Provider:
        def complete(self, prompt, **kwargs):
            return next(replies)

    proposal = Planner(provider=_Provider()).propose(
        "p", budget=RunBudget(), purpose="exploration", view={})
    assert proposal.action == "finish"
    assert proposal.truncated_retry is True
    assert proposal.to_dict()["truncated_retry"] is True


def test_malformed_json_that_was_not_truncated_is_still_a_contract_failure():
    """The distinction has to hold in both directions, or every model defect becomes an
    allowance problem and nothing gets fixed."""
    from app.planner import Planner, ProposalRejected, ResponseTruncated
    from app.provider import Completion, CredentialTier, RunBudget, Usage

    class _Provider:
        calls = 0

        def complete(self, prompt, **kwargs):
            type(self).calls += 1
            return Completion("not json at all", Usage(), "m", CredentialTier.FREE,
                              cached=False, seconds=0.1, finish_reason="STOP")

    with pytest.raises(ProposalRejected) as caught:
        Planner(provider=_Provider()).propose("p", budget=RunBudget(),
                                              purpose="exploration", view={})
    assert not isinstance(caught.value, ResponseTruncated)
    assert _Provider.calls == 1, "a malformed reply must not be re-asked"


# --- A17.9: the re-ask is charged to the run that made it ---------------------------

def _truncating_provider(monkeypatch, replies):
    """A real `Provider` with only the network call replaced.

    The accounting under test lives in `Provider.complete` — the call budget, the token
    budget and the spend ledger are all touched there. A stub provider would exercise the
    planner's retry and none of the accounting it is supposed to be charged to, which is
    exactly the fiction A17.9 is about.
    """
    from app.provider import CredentialPolicy, CredentialTier, Provider

    provider = Provider(policy=CredentialPolicy.DEVELOPMENT)
    monkeypatch.setattr(provider, "available_tiers", lambda: [CredentialTier.FREE])
    monkeypatch.setattr(provider, "key_for", lambda tier: "test-key")
    monkeypatch.setattr(provider, "_pace", lambda: 0.0)
    monkeypatch.setattr(provider, "_record_spend", lambda completion: None)
    monkeypatch.setattr(provider, "_check_spend", lambda: None)
    provider.cache_enabled = False
    served = iter(replies)
    monkeypatch.setattr(provider, "_call",
                        lambda prompt, key, tier, cap: next(served))
    return provider


def _completion(text, finish, tokens=120):
    from app.provider import Completion, CredentialTier, Usage

    usage = Usage(input_tokens=1000, output_tokens=tokens)
    usage.usd = (1000 * 0.10 + tokens * 0.40) / 1_000_000
    return Completion(text, usage, "m", CredentialTier.FREE, cached=False, seconds=0.1,
                      finish_reason=finish)


TRUNCATED = '{"action": "finish", "args": {}, "why": "I reviewed the'
GOOD = ('{"action": "finish", "args": {}, "why": "done", "strategy": "F1",'
        ' "diagnosis": "none"}')


def test_the_re_ask_counts_against_the_call_budget_and_the_cost(monkeypatch):
    """A retry that is free in the accounting makes both budgets fiction: the run reports
    one call where it made two, and a cost that omits the more expensive of the two."""
    from app.planner import Planner
    from app.provider import RunBudget

    provider = _truncating_provider(monkeypatch, [_completion(TRUNCATED, "MAX_TOKENS"),
                                                  _completion(GOOD, "STOP", tokens=40)])
    budget = RunBudget()

    proposal = Planner(provider=provider).propose("p", budget=budget,
                                                  purpose="exploration", view={})

    assert proposal.truncated_retry is True
    assert budget.exploration_calls == 2
    assert budget.output_tokens == 160
    assert budget.usd == pytest.approx((2000 * 0.10 + 160 * 0.40) / 1_000_000)


def test_a_run_out_of_calls_cannot_borrow_one_to_retry_a_truncation(monkeypatch):
    """The budget is fail-closed, and the re-ask is inside it rather than beside it."""
    from app.config import settings
    from app.planner import Planner
    from app.provider import ProviderError, RunBudget

    provider = _truncating_provider(monkeypatch, [_completion(TRUNCATED, "MAX_TOKENS"),
                                                  _completion(GOOD, "STOP")])
    budget = RunBudget(exploration_calls=settings.budgets.exploration_calls - 1)

    with pytest.raises(ProviderError) as caught:
        Planner(provider=provider).propose("p", budget=budget, purpose="exploration",
                                           view={})
    assert "exploration call budget" in str(caught.value)
    assert budget.exploration_calls == settings.budgets.exploration_calls


def test_a_second_truncation_ends_the_step_as_output_truncated(monkeypatch):
    """Not `internal_error`, and not `provider_error`: our own cap, named as ours."""
    from app.models import FailureClass
    from app.planner import Planner, ResponseTruncated
    from app.provider import RunBudget

    provider = _truncating_provider(monkeypatch, [_completion(TRUNCATED, "MAX_TOKENS"),
                                                  _completion(TRUNCATED, "MAX_TOKENS")])
    budget = RunBudget()

    with pytest.raises(ResponseTruncated):
        Planner(provider=provider).propose("p", budget=budget, purpose="exploration",
                                           view={})
    assert budget.exploration_calls == 2
    assert FailureClass("output_truncated") is FailureClass.OUTPUT_TRUNCATED


def test_the_cost_a_run_reports_carries_the_output_cap_it_was_measured_under():
    """Output is charged at several times input on this model family, so a cost range
    measured under one cap does not describe another (A17.10)."""
    from app.config import settings
    from app.models import BudgetUse

    recorded = BudgetUse(usd=0.0021).to_dict()
    assert recorded["output_cap_per_call"] == settings.budgets.max_output_tokens_per_call
    assert recorded["output_cap_per_run"] == settings.budgets.max_output_tokens_per_run


# --- a rate limit is a window, not a verdict on the key -----------------------------

def test_a_rate_limited_tier_is_tried_again_after_its_window(monkeypatch):
    """RPM resets in a minute. Marking the tier dead for the life of the process meant one
    burst disabled the model path until the next deploy — every run after it reported
    `provider_error`, which is neither what happened nor a class anyone can act on."""
    from app.config import settings
    from app.provider import (
        CredentialPolicy, CredentialTier, Provider, ProviderQuotaExhausted, RunBudget,
    )

    provider = Provider(policy=CredentialPolicy.DEVELOPMENT)
    monkeypatch.setattr(provider, "available_tiers", lambda: [CredentialTier.FREE])
    monkeypatch.setattr(provider, "key_for", lambda tier: "test-key")
    monkeypatch.setattr(provider, "_check_spend", lambda: None)
    provider._quota_exhausted[CredentialTier.FREE] = (
        __import__("time").time() + settings.provider.quota_cooldown_seconds)

    # Inside the window: refused, and refused as a quota condition.
    with pytest.raises(ProviderQuotaExhausted) as caught:
        provider.complete("p", budget=RunBudget(), purpose="exploration")
    assert "rate-limited right now" in str(caught.value)
    assert caught.value.failure_class.value == "provider_quota"

    # Past it: tried again rather than written off.
    provider._quota_exhausted[CredentialTier.FREE] = 0.0
    monkeypatch.setattr(provider, "_pace", lambda: 0.0)
    monkeypatch.setattr(provider, "_record_spend", lambda completion: None)
    monkeypatch.setattr(provider, "_call",
                        lambda prompt, key, tier, cap: _completion(GOOD, "STOP"))
    assert provider.complete("p", budget=RunBudget(), purpose="exploration").text == GOOD

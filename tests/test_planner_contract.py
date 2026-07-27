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
    store.record_spend("paid", 6.0, 1000, 100)          # already over the USD 5 ceiling

    provider = Provider(policy=CredentialPolicy.DEVELOPMENT, ledger=store)
    with pytest.raises(ProviderQuotaExhausted) as exc:
        provider.complete("anything", budget=RunBudget(), purpose="exploration")

    assert exc.value.failure_class is FailureClass.PROVIDER_QUOTA
    assert "self-approval limit" in str(exc.value)
    # ...and the state that decided it survives a restart, because it is on disk.
    assert Store(tmp_path / "runs.sqlite3",
                 tmp_path / "artifacts").spend()["cumulative_usd"] == 6.0


def test_the_daily_ceiling_is_separate_from_the_cumulative_one(tmp_path, monkeypatch):
    from app.provider import ProviderQuotaExhausted
    from app.store import Store

    monkeypatch.setenv("REQUIRE_PERSISTENT_STORE", "false")
    store = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    store.record_spend("paid", 1.5, 1000, 100)          # under USD 5, over the daily USD 1

    provider = Provider(policy=CredentialPolicy.DEVELOPMENT, ledger=store)
    with pytest.raises(ProviderQuotaExhausted) as exc:
        provider.complete("anything", budget=RunBudget(), purpose="exploration")
    assert "Today's provider spend ceiling" in str(exc.value)

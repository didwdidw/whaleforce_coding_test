"""Which path runs, and why it must be recorded (A13.4).

The model-driven loop used to hide behind the phrase "use the planner". A reviewer
submitting a promised task in plain English got a hard-coded script — the mechanism being
graded, invisible unless you knew the password. So model-driven is the default for real-site
operations, and the three jobs the deterministic script keeps are enumerated here rather
than left to whoever reads the branch: the fixture demonstrations, which must keep working
with no provider at all; the fallback when no credential is readable; and the baseline the
analysis report compares against.

The decision is recorded on the run, not only in the trace, because a success rate that
mixes the two paths describes neither.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.executor import Executor, Plan
from app.postcondition import ClaimSpec, Postcondition, Relation

WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


class _Provider:
    def __init__(self, configured: bool) -> None:
        self._configured = configured

    def configured(self) -> bool:
        return self._configured


def _executor(*, credential: bool = True) -> Executor:
    executor = Executor.__new__(Executor)
    executor._provider = _Provider(credential)
    return executor


def _plan(entry_url: str) -> Plan:
    pc = Postcondition(goal="g", operation="op", target_url=entry_url,
                       claims=(ClaimSpec(name="v", label="UPC",
                                         relation=Relation.TABLE_ROW_CELL,
                                         value_type="string"),))
    return Plan(operation="op", label="l", postcondition=pc, steps=(), entry_url=entry_url)


def test_a_real_site_operation_is_model_driven_by_default():
    """A-35: plain language, no special phrasing, no magic word."""
    planned, why = _executor()._choose_path(_plan(WIKI), False, False)
    assert planned and "default" in why


def test_the_fixture_demonstrations_never_depend_on_a_provider():
    """They are what a visitor sees when the free tier is spent. If they needed the model,
    an exhausted quota would empty the frontend of everything inspectable."""
    planned, why = _executor()._choose_path(_plan(settings.fixture_base_url + "/browse"),
                                            False, False)
    assert not planned and "fixture" in why


def test_no_credential_falls_back_to_the_script_rather_than_failing():
    planned, why = _executor(credential=False)._choose_path(_plan(WIKI), False, False)
    assert not planned and "credential" in why


def test_the_deterministic_path_can_be_asked_for_on_a_real_site():
    """It is the comparison baseline. Getting it by turning the provider off would change
    two things at once and measure neither."""
    planned, why = _executor()._choose_path(_plan(WIKI), False, True)
    assert not planned and "baseline" in why


def test_asking_for_the_planner_still_wins():
    planned, why = _executor(credential=False)._choose_path(
        _plan(settings.fixture_base_url), True, True)
    assert planned and why == "requested"


def test_a_policy_demonstration_has_no_model_driven_form():
    planned, why = _executor()._choose_path(_plan(""), False, False)
    assert not planned and "policy demonstration" in why


@pytest.mark.parametrize("phrase", ["use the planner", "without the planner",
                                    "scripted mode", "seed mu2-text"])
def test_path_directives_are_not_part_of_the_task(phrase):
    """`seed mu6-overlay` once made every task look like an overlay task. A directive is
    metadata about how to run, and routing on it answers a question nobody asked."""
    executor = Executor.__new__(Executor)
    plain = "Open the product detail page and read its labelled product information"
    assert executor.route(plain) == executor.route(f"{plain}, {phrase}")

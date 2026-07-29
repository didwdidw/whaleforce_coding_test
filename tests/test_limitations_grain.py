"""The executable limitations list has to check everything the entry publishes.

`eval.limitations_check` re-ran all seven entries and reported all seven reproducing while
`L-1`'s remediated phrasing published `budget_exhausted` and the run ended
`verification_mismatch`. The check was not wrong about what it compared — it compared
terminal status and, for a remedy, nothing else. **A check looser than the claim it stands
behind is worse than no check**, because the report it produces is read as coverage.

The comparison grain is the thing under test here, not any one entry's label.
"""

from __future__ import annotations

from app.limitations import LIMITATIONS, UNPINNED
from eval.limitations_check import _compare


def _seen(status: str, failure_class: str | None = None) -> dict:
    return {"terminal_status": status, "failure_class": failure_class, "timed_out": False}


def test_a_wrong_failure_class_is_a_discrepancy_even_when_the_status_matches():
    ok, why = _compare("failed", "budget_exhausted", _seen("failed", "verification_mismatch"))
    assert not ok
    assert "budget_exhausted" in why and "verification_mismatch" in why


def test_an_entry_claiming_no_class_is_held_to_that_claim():
    """`None` is a claim — that the outcome carries no class — and it used to be the value
    that turned the comparison off, which is how the field went unchecked."""
    assert _compare("succeeded_verified", None, _seen("succeeded_verified"))[0]
    assert not _compare("succeeded_verified", None,
                        _seen("succeeded_verified", "postcondition_unmet"))[0]


def test_declining_to_pin_a_class_has_to_be_said_out_loud():
    ok, why = _compare("failed", UNPINNED, _seen("failed", "anything_at_all"))
    assert ok and not why


def test_the_remedy_half_is_compared_at_the_same_grain_as_the_entry():
    """The remedy is part of what the entry says (A25.1), so it is checked like the entry.
    This asserts the checker reads the published remedy class at all — passing `None` for
    it unconditionally is exactly the defect, and it looks identical from the report."""
    import inspect

    from eval import limitations_check

    source = inspect.getsource(limitations_check.run)
    assert "limit.remedy_failure_class" in source, (
        "the remedy's published class must reach _compare, or the field is decoration")


def test_every_entry_that_publishes_a_remedy_publishes_what_it_ends_as():
    for limit in LIMITATIONS:
        if not limit.remedy_task:
            continue
        assert limit.remedy_outcome, f"{limit.id} publishes a remedy with no outcome"
        # `None` is allowed and means "no class"; what is not allowed is a status-only
        # remedy whose class nobody decided, because that is unfalsifiable prose.
        assert limit.remedy_failure_class is None or isinstance(
            limit.remedy_failure_class, str)


def test_a_pinned_class_is_a_value_from_the_closed_set():
    """A typo in a published class is a claim nothing can reproduce."""
    from app.models import FailureClass

    known = {f.value for f in FailureClass} | {UNPINNED}
    for limit in LIMITATIONS:
        for field in (limit.failure_class, limit.remedy_failure_class):
            assert field is None or field in known, f"{limit.id}: {field!r}"

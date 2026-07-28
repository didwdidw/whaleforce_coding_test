"""Policy tests: egress guard, configuration fail-safes, and executor routing.

robots.txt matching semantics live in `test_robots_semantics.py` — Amendment 10 requires
them to be their own suite, because the defect that prompted it could not have been caught
by any dataset outcome.

Run with: `.venv/bin/python -m pytest tests/ -q`
"""

from __future__ import annotations

import pytest

from app import egress

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "data:text/html,<h1>x",
    "blob:https://example.com/x",
    "ftp://example.com/x",
    "https://127.0.0.1/",
    "https://10.0.0.5/",
    "https://192.168.1.1/",
    "https://169.254.169.254/latest/meta-data/",   # cloud metadata
    "https://[::1]/",
    "https://[::ffff:10.0.0.1]/",                  # IPv4-mapped private
    "https://100.64.1.1/",                         # CGNAT
    "http://books.toscrape.com/",                  # plaintext without a declared reason
])
def test_egress_blocks(url):
    assert egress.check_url(url, allow_private=False).allowed is False, url


@pytest.mark.parametrize("url", [
    "https://en.wikipedia.org/wiki/Apple_Inc.",
    "https://books.toscrape.com/",
    "https://www.sec.gov/Archives/edgar/data/320193/",
])
def test_egress_allows_declared_targets(url):
    assert egress.check_url(url, allow_private=False).allowed is True, url


def test_egress_names_the_range_it_blocked():
    """The trace has to say which range stopped it, not just that policy did."""
    d = egress.check_url("https://169.254.169.254/", allow_private=False)
    assert "link-local" in d.reason


def test_production_refuses_to_start_with_the_ssrf_guard_off(monkeypatch):
    """The flag disables SSRF protection and the system would keep working normally with
    no visible sign, so a misconfiguration must be a startup failure, not a silent one."""
    from app.config import Settings

    monkeypatch.setenv("ALLOW_PRIVATE_EGRESS", "true")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SystemExit) as excinfo:
        Settings().validate_or_die()
    assert "ALLOW_PRIVATE_EGRESS" in str(excinfo.value)


def test_unset_app_env_is_treated_as_production(monkeypatch):
    """A missing or misspelled APP_ENV must not be read as dev — dev is the only value
    that can switch the guard off."""
    from app.config import Settings

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("ALLOW_PRIVATE_EGRESS", "true")
    with pytest.raises(SystemExit):
        Settings().validate_or_die()

    monkeypatch.setenv("APP_ENV", "prod-eu")   # not a recognised dev value
    with pytest.raises(SystemExit):
        Settings().validate_or_die()


def test_dev_may_relax_the_guard_but_says_so(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_PRIVATE_EGRESS", "true")
    s = Settings()
    s.validate_or_die()
    guard = s.egress_guard_state()
    assert guard["ssrf_guard_enabled"] is False
    assert "DISABLED" in guard["note"]


def test_guard_state_is_recorded_for_audit(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("ALLOW_PRIVATE_EGRESS", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    guard = Settings().egress_guard_state()
    assert guard["ssrf_guard_enabled"] is True
    assert guard["app_env"] == "production"


# --- executor routing -------------------------------------------------------------
#
# Both defects below shipped to the deployed system and were caught only by reading the
# candidate each run produced. Neither raised an error: one operation answered a different
# operation's question, and the other searched for a sentence fragment and reported "0
# results". A wrong answer that looks like an answer is the failure this product exists to
# prevent, so the routing is pinned here.

@pytest.mark.parametrize("task,operation", [
    ("Search the fixture catalogue for lantern", "GS-1"),
    ("Find 'Morse Lamp' in the fixture catalogue", "GS-1"),
    ("Browse the fixture catalogue and page forward to page 3", "GS-2"),
    # "gated page" contains "page"; a bare "page" marker routed this to the paginator,
    # which returned a pager reading for a task that asked for a reference code.
    ("Dismiss the overlay on the fixture gated page and read the reference code", "GS-3"),
    ("Dismiss the modal on the fixture gated page then reveal the code", "GS-3"),
    ("Read the fixture customer notes page", "GS-injection"),
])
def test_task_routes_to_the_operation_it_names(task, operation):
    from app.executor import Executor

    plan = Executor._select_plan(Executor.__new__(Executor), task)
    assert plan is not None, task
    assert plan.operation == operation, f"{task!r} routed to {plan.operation}"


def test_unrecognised_task_routes_nowhere_rather_than_guessing():
    from app.executor import Executor

    assert Executor._select_plan(Executor.__new__(Executor), "What is the capital of France?") is None


@pytest.mark.parametrize("task,term", [
    # The greedy character class returned "the fixture catalogue for lant" here.
    ("search the fixture catalogue for lantern", "lantern"),
    ("find 'morse lamp' in the catalogue", "morse lamp"),
    ('search for "brass compass"', "brass compass"),
    ("search for compass", "compass"),
    ("look for barometer", "barometer"),
    # Names no term: guessing one returns a result set nobody asked about.
    ("search the catalogue", None),
    ("search", None),
])
def test_search_term_is_extracted_or_refused(task, term):
    from app.executor import Executor

    assert Executor._search_term(task) == term

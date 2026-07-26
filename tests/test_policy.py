"""Policy tests: egress and robots.

These exist because both components failed silently in the direction of permission, which
is the failure mode neither can be allowed to have. Run with:

    .venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import pytest

from app import egress
from app.robots import RobotsRules

# The shape that defeats urllib.robotparser: a blank line inside a `User-agent: *` group.
# It ends the group there, discarding every rule after it — including the two that
# www.sec.gov's real robots.txt places in exactly this position.
SEC_SHAPED = """User-agent: *
Allow: /core/*.css$
Disallow: /core/
Disallow: /profiles/
Disallow: /search/

#SEC
Allow: /Archives/edgar/data
Disallow: /cgi-bin
Disallow: /Archives/edgar/vprr/bin
"""

WIKI_SHAPED = """User-agent: WebReaper
Disallow: /

User-agent: SemrushBot
Crawl-delay: 5

User-agent: *
Allow: /w/load.php?
Disallow: /w/
Disallow: /api/
Disallow: /wiki/Special:
"""


@pytest.mark.parametrize("path,allowed", [
    ("/search/anything", False),
    ("/cgi-bin/browse-edgar", False),          # after the blank line
    ("/Archives/edgar/vprr/bin/x", False),     # after the blank line
    ("/Archives/edgar/data/320193/", True),    # after the blank line
    ("/core/style.css", True),                 # Allow: /core/*.css$ beats Disallow: /core/
    ("/core/style.css.map", False),            # the $ anchor must not match past .css
    ("/unlisted", True),
])
def test_rules_survive_a_blank_line(path, allowed):
    ok, _ = RobotsRules(SEC_SHAPED).match("agent", path)
    assert ok is allowed, path


def test_longest_match_wins_not_first_listed():
    rules = RobotsRules("User-agent: *\nDisallow: /a\nAllow: /a/b\n")
    assert rules.match("x", "/a/c")[0] is False
    assert rules.match("x", "/a/b/c")[0] is True


def test_allow_wins_an_equal_length_tie():
    rules = RobotsRules("User-agent: *\nDisallow: /x\nAllow: /x\n")
    assert rules.match("agent", "/x/y")[0] is True


def test_named_agent_group_does_not_leak_to_us():
    """Wikipedia's Crawl-delay belongs to SemrushBot; its `Disallow: /` for WebReaper must
    not apply to us either."""
    rules = RobotsRules(WIKI_SHAPED)
    assert rules.match("WhaleforceCodingTest-Task1/0.1", "/wiki/Apple_Inc.")[0] is True
    assert rules.match("WhaleforceCodingTest-Task1/0.1", "/wiki/Special:Search")[0] is False
    assert rules.match("WebReaper/1.0", "/wiki/Apple_Inc.")[0] is False


def test_query_string_is_part_of_the_matched_path():
    rules = RobotsRules("User-agent: *\nDisallow: /page?x=1\n")
    assert rules.match("a", "/page?x=1")[0] is False
    assert rules.match("a", "/page?x=2")[0] is True


def test_empty_disallow_permits_everything():
    assert RobotsRules("User-agent: *\nDisallow:\n").match("a", "/anything")[0] is True


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

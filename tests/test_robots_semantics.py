"""robots.txt matching semantics (Amendment 10, A10.1–A10.6).

These are tests of the **semantics**, not of dataset outcomes, and that distinction is the
point of A10.6. The defect that prompted the amendment — `urllib.robotparser` ending a
user-agent group at a blank line — would have left DEV-13 passing, because the rule DEV-13
targets happens to sit before the blank line in Wikipedia's file. A case that passes for the
wrong reason is indistinguishable from one that passes for the right one, so no volume of
eval cases could have caught it.

`tests/fixtures/sec.gov-robots.txt` is the live body that exposed it, vendored verbatim
(A10.6). `tests/fixtures/en.wikipedia.org-robots.txt` is included because its named-bot
groups are the other half of the grouping rules.
"""

from __future__ import annotations

import pathlib

import pytest

from app.robots import RobotsCache, RobotsRules

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SEC = (FIXTURES / "sec.gov-robots.txt").read_text(encoding="utf-8")
WIKI = (FIXTURES / "en.wikipedia.org-robots.txt").read_text(encoding="utf-8")
UA = "WhaleforceCodingTest-Task1/0.1 (contact: didwdidw0309@gmail.com)"


# --- A10.2: the banned component ---------------------------------------------------

def test_urllib_robotparser_is_not_imported_anywhere():
    """A10.2 bans it outright. Checked by parsing imports rather than grepping text, so
    the comments that document the ban do not trip it — and so a re-introduction cannot
    hide behind an alias. Re-introduction would otherwise be silent: the parser
    under-blocks without ever raising."""
    import ast

    offenders = []
    for path in sorted(pathlib.Path(".").glob("*/*.py")):
        if path.parts[0] not in ("app", "fixture", "preflight"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [(path, a.name) for a in node.names
                              if a.name.startswith("urllib.robotparser")]
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("urllib.robotparser"):
                    offenders.append((path, mod))
                elif mod == "urllib":
                    offenders += [(path, "urllib." + a.name) for a in node.names
                                  if a.name == "robotparser"]
    assert not offenders, (
        f"urllib.robotparser is imported: {offenders}. It violates A10.1.1 "
        f"(first-match), A10.1.3 (no wildcards) and A10.1.4 (blank line ends a group).")


# --- A10.1.4: groups end only at the next User-agent -------------------------------

def test_sec_rules_after_a_blank_line_are_still_in_the_group():
    """The exact defect. In the live file `User-agent: *` is at line 16, the first blank
    line inside its group is at 74, and both of these sit after it."""
    rules = RobotsRules(SEC)
    assert rules.match(UA, "/cgi-bin/browse-edgar").allowed is False
    assert rules.match(UA, "/Archives/edgar/data/320193/").allowed is True


def test_sec_comment_lines_do_not_terminate_the_group():
    """`#SEC` sits between the blank line and the rules that follow it."""
    assert "#SEC" in SEC
    assert RobotsRules(SEC).match(UA, "/Archives/edgar/vprr/bin/x").allowed is False


def test_group_does_terminate_at_the_next_user_agent():
    doc = "User-agent: alpha\nDisallow: /\n\nUser-agent: beta\nAllow: /\n"
    rules = RobotsRules(doc)
    assert rules.match("alpha-bot", "/anything").allowed is False
    assert rules.match("beta-bot", "/anything").allowed is True


def test_named_group_rules_do_not_leak_to_other_agents():
    """Wikipedia disallows everything for WebReaper; that must not apply to us."""
    rules = RobotsRules(WIKI)
    assert rules.match("WebReaper/1.0", "/wiki/Apple_Inc.").allowed is False
    assert rules.match(UA, "/wiki/Apple_Inc.").allowed is True
    assert rules.match(UA, "/wiki/Special:Search").allowed is False
    assert rules.match(UA, "/w/index.php").allowed is False


# --- A10.1.1 / A10.1.2: longest match, Allow wins ties ----------------------------

def test_longest_match_wins_not_first_listed():
    rules = RobotsRules("User-agent: *\nDisallow: /a\nAllow: /a/b\n")
    assert rules.match("x", "/a/c").allowed is False
    assert rules.match("x", "/a/b/c").allowed is True
    assert rules.match("x", "/a/b/c").pattern == "/a/b"


def test_equal_length_tie_goes_to_allow():
    rules = RobotsRules("User-agent: *\nDisallow: /x\nAllow: /x\n")
    d = rules.match("x", "/x/y")
    assert d.allowed is True and d.directive == "Allow"


def test_order_in_the_file_does_not_change_the_outcome():
    a = RobotsRules("User-agent: *\nAllow: /a/b\nDisallow: /a\n")
    b = RobotsRules("User-agent: *\nDisallow: /a\nAllow: /a/b\n")
    assert a.match("x", "/a/b/c").allowed == b.match("x", "/a/b/c").allowed is True


# --- A10.1.3: wildcards -----------------------------------------------------------

def test_star_matches_any_sequence():
    rules = RobotsRules("User-agent: *\nDisallow: /a/*/private\n")
    assert rules.match("x", "/a/anything/private").allowed is False
    assert rules.match("x", "/a/b/c/private").allowed is False
    assert rules.match("x", "/a/b/public").allowed is True


def test_dollar_anchors_the_end_of_the_path():
    rules = RobotsRules("User-agent: *\nDisallow: /core/\nAllow: /core/*.css$\n")
    assert rules.match("x", "/core/style.css").allowed is True
    assert rules.match("x", "/core/style.css.map").allowed is False


def test_sec_css_allow_uses_a_dollar_anchor_in_the_live_file():
    assert "Allow: /core/*.css$" in SEC
    rules = RobotsRules(SEC)
    assert rules.match(UA, "/core/x.css").allowed is True
    assert rules.match(UA, "/core/x.css.map").allowed is False


# --- A10.4: every decision cites its rule -----------------------------------------

@pytest.mark.parametrize("path,directive,pattern", [
    ("/cgi-bin/browse-edgar", "Disallow", "/cgi-bin"),
    ("/Archives/edgar/data/1/", "Allow", "/Archives/edgar/data"),
    ("/search/anything", "Disallow", "/search/"),
])
def test_matched_rule_is_reported(path, directive, pattern):
    d = RobotsRules(SEC).match(UA, path)
    assert (d.directive, d.pattern) == (directive, pattern)
    assert d.group_user_agent == "*"
    assert d.rule == f"{directive}: {pattern}"


def test_no_rule_matched_is_stated_explicitly_not_left_blank():
    """An allow with nothing to cite is exactly what could not be audited before."""
    d = RobotsRules(SEC).match(UA, "/some/unlisted/path")
    assert d.allowed is True
    assert d.directive is None and d.pattern is None
    assert d.rule == "no rule matched"


def test_empty_disallow_permits_everything():
    assert RobotsRules("User-agent: *\nDisallow:\n").match("a", "/anything").allowed is True


# --- A10.3: the fail-closed boundary ----------------------------------------------

class _StubCache(RobotsCache):
    """Substitutes a fetch outcome so the boundary is tested without a network."""

    def __init__(self, entry):
        super().__init__()
        self._stub = entry

    def _fetch(self, origin):  # noqa: D102 - overrides the network call
        return self._stub


def _entry(rules, status, note=""):
    from app.robots import RobotsEntry
    import time as _t
    return RobotsEntry(rules, [], _t.time(), status, note)


def test_404_means_no_restrictions_not_a_failure_to_fetch():
    """books.toscrape.com serves no robots.txt. Treating that as unfetchable would refuse
    the whole origin and take OP-6 and OP-7 with it."""
    cache = _StubCache(_entry(None, 404, "no robots.txt (404)"))
    d = cache.decide("https://books.toscrape.com/catalogue/x.html", UA)
    assert d.allowed is True
    assert d.source == "no_robots_txt"
    assert "404" in d.rule


@pytest.mark.parametrize("status,note", [
    (500, "robots.txt returned HTTP 500"),
    (503, "robots.txt returned HTTP 503"),
    (None, "robots.txt could not be fetched: TimeoutError"),
])
def test_unfetchable_robots_fails_closed(status, note):
    cache = _StubCache(_entry(None, status, note))
    d = cache.decide("https://example.com/anything", UA)
    assert d.allowed is False
    assert d.source == "unfetchable"


def test_a_200_that_is_not_a_robots_txt_fails_closed():
    """A captive portal or error page parses to zero groups and would otherwise read as
    'nothing is disallowed'."""
    cache = _StubCache(_entry(None, 200, "body is not a robots.txt"))
    d = cache.decide("https://example.com/anything", UA)
    assert d.allowed is False
    assert d.source == "unparseable"


def test_availability_of_the_policy_file_is_not_a_reason_to_ignore_the_policy():
    allowed_404 = _StubCache(_entry(None, 404)).decide("https://a.example/x", UA).allowed
    refused_500 = _StubCache(_entry(None, 500)).decide("https://a.example/x", UA).allowed
    assert allowed_404 is True and refused_500 is False


# --- A10.5: the same policy applies to the server-side fetcher --------------------

def test_server_fetcher_uses_the_same_robots_decision():
    """The defect was found on SEC, which the browser tier never visits."""
    from app.fetcher import ServerFetcher

    f = ServerFetcher(robots=_StubCache(_entry(RobotsRules(SEC), 200)))
    _, blocked = f.check("https://www.sec.gov/cgi-bin/browse-edgar")
    _, allowed = f.check("https://www.sec.gov/Archives/edgar/data/320193/")
    assert blocked.allowed is False and blocked.pattern == "/cgi-bin"
    assert allowed.allowed is True and allowed.pattern == "/Archives/edgar/data"


def test_server_fetcher_refuses_a_disallowed_path_before_requesting_it():
    from app.fetcher import FetchRefused, ServerFetcher

    f = ServerFetcher(robots=_StubCache(_entry(RobotsRules(SEC), 200)))
    with pytest.raises(FetchRefused) as exc:
        f.fetch("https://www.sec.gov/cgi-bin/browse-edgar")
    assert exc.value.failure_class == "robots_disallowed"
    assert "Disallow: /cgi-bin" in exc.value.reason


def test_server_fetcher_declares_a_contact_user_agent():
    """SEC returns 403 without one, which presents as a network-level block (A9.8)."""
    from app.fetcher import ServerFetcher

    assert "@" in ServerFetcher().user_agent


# --- M4 gate: enforcement on a Disallowed path of a real site ---------------------

def test_wikipedia_disallows_the_special_namespace_and_the_rule_is_quotable():
    """The M4 gate's robots demonstration, at the level where it is deterministic.

    "Which pages link to this article" is an ordinary, useful question, and Wikipedia
    answers it at `Special:WhatLinksHere` — a path its robots.txt Disallows for the wildcard
    group. So the refusal is not us declining something nobody wanted; it is a rule from a
    site we do not control, applied to a task a person would actually ask, and quoted back
    so that someone who does not trust us can check it.
    """
    rules = RobotsRules(WIKI)
    blocked = rules.match(UA, "/wiki/Special:WhatLinksHere/List_of_S%26P_500_companies")
    assert blocked.allowed is False
    assert blocked.rule == "Disallow: /wiki/Special:"
    assert blocked.group_user_agent == "*"

    # ...and the article the promised records use is not blocked by the same file, which is
    # the half that shows the matcher is discriminating rather than simply refusing.
    allowed = rules.match(UA, "/wiki/List_of_S%26P_500_companies")
    assert allowed.allowed is True


def test_the_percent_encoded_spelling_of_the_same_namespace_is_also_disallowed():
    """`/wiki/Special%3A` is listed separately in the file, and a matcher that decoded the
    path before comparing would silently allow one of the two spellings."""
    rules = RobotsRules(WIKI)
    assert rules.match(UA, "/wiki/Special%3ARandom").allowed is False

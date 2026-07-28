"""robots.txt as a binding constraint (S-2.3).

A Disallowed path is refused before any navigation, and the **matching rule** is reported
so a user can see which line stopped them rather than being told "policy" (DEV-13).

Two facts measured at M0 shape this:
  - Wikipedia's `Crawl-delay: 5` belongs to the `SemrushBot` block, not `*`, so no
    crawl-delay applies to us there. Per-origin pacing is our own voluntary limit and the
    README must not present it as robots compliance (A9.9).
  - SEC returns 403 to a request with no declared contact User-Agent, and the body arrives
    gzipped, so the fetcher declares its UA and decompresses before reporting (A9.8).
"""

from __future__ import annotations

import gzip
import ssl
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field, replace
from typing import Any
import re
from urllib.parse import urlsplit

from app.config import settings


def _ssl_context() -> ssl.SSLContext:
    """Prefer certifi's bundle: some Python builds ship without usable system CA paths,
    and a TLS failure here must not be mistaken for a policy answer."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _looks_like_markup(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith("<") or "<html" in head or "<!doctype" in head


def _decode(raw: bytes, encoding: str | None) -> bytes:
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def product_token(user_agent: str) -> str:
    """Our identity as robots.txt sees it: the product token, lowercased.

    `WhaleforceCodingTest-Task1/0.1 (contact: …)` identifies itself as
    `whaleforcecodingtest-task1`. The version and the comment are not part of what a group's
    user-agent line is compared against.
    """
    return (user_agent or "").strip().split("/")[0].split()[0].lower() if user_agent else ""


class RobotsRules:
    """An RFC 9309 matcher.

    `urllib.robotparser` is not usable here: it ends a group at a blank line, so on
    `www.sec.gov/robots.txt` — where the SEC-specific block sits after a blank line inside
    the `User-agent: *` group — every rule in it is discarded. That silently drops
    `Disallow: /cgi-bin` and `Allow: /Archives/edgar/data`, both of which the site policy in
    §3.4 depends on. It also matches by first-listed rule rather than longest match, and
    ignores `*` and `$` wildcards entirely.

    Implemented here instead: groups end only at the next user-agent line, the longest
    matching pattern wins, Allow beats Disallow on an equal-length match, and `*` and `$`
    are honoured.
    """

    def __init__(self, text: str) -> None:
        self.groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        expecting_agent = True
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue  # A blank line does not end a group (RFC 9309 §2.2.1).
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                # A user-agent line after a rule starts a new group.
                if not expecting_agent:
                    self.groups.append((agents, rules))
                    agents, rules = [], []
                    expecting_agent = True
                agents.append(value.lower())
            elif key in ("allow", "disallow"):
                expecting_agent = False
                if value or key == "disallow":
                    # "Disallow:" with an empty value allows everything and is skipped;
                    # an empty Allow is meaningless.
                    if value:
                        rules.append((key == "allow", value))
        if agents or rules:
            self.groups.append((agents, rules))

    def _rules_for(self, user_agent: str) -> tuple[list[tuple[bool, str]], str | None]:
        """Most specific matching group and its user-agent, falling back to `*`.

        RFC 9309 §2.2.1 matches a group's user-agent as a case-insensitive **prefix of our
        product token**, and takes no wildcards there. Both halves are load-bearing:

        - Prefix, not substring. `Disallow` under a group named `bot` was applying to us for
          being a `…Robot/1.0`, which is a rule nobody wrote for us.
        - No wildcards. `openlibrary.org` publishes a `User-agent: *bot` group with a
          `Crawl-delay: 10`. Read as a glob it matches every crawler with "bot" in its name;
          read as RFC 9309 requires, `*bot` is a product token no agent is called, it
          matches nothing, and we fall to `*` — which is the group that was actually
          written for us.
        """
        token = product_token(user_agent)
        best: list[tuple[bool, str]] | None = None
        best_agent: str | None = None
        best_len = -1
        star: list[tuple[bool, str]] | None = None
        for agents, rules in self.groups:
            for agent in agents:
                if agent == "*":
                    star = rules if star is None else star + rules
                elif agent and token.startswith(agent) and len(agent) > best_len:
                    best, best_agent, best_len = rules, agent, len(agent)
        if best is not None:
            return best, best_agent
        return (star or []), ("*" if star is not None else None)

    @staticmethod
    def _to_regex(pattern: str) -> re.Pattern:
        out, anchored = [], pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        for ch in body:
            out.append(".*" if ch == "*" else re.escape(ch))
        return re.compile("^" + "".join(out) + ("$" if anchored else ""))

    def match(self, user_agent: str, path: str) -> "RobotsDecision":
        """Longest match wins; Allow wins ties. The deciding rule is always reported."""
        rules, group_agent = self._rules_for(user_agent)
        decision: tuple[bool, str] | None = None
        best_len = -1
        for allow, pattern in rules:
            if not self._to_regex(pattern).match(path):
                continue
            weight = len(pattern.rstrip("$"))
            if weight > best_len or (weight == best_len and allow):
                decision, best_len = (allow, pattern), weight
        if decision is None:
            # Not an absence of evidence to paper over: "no rule matched" is itself the
            # citable reason this path is allowed (A10.4).
            return RobotsDecision(True, None, None, group_agent, "no rule matched")
        allow, pattern = decision
        return RobotsDecision(allow, "Allow" if allow else "Disallow", pattern, group_agent,
                              f"{'Allow' if allow else 'Disallow'}: {pattern}")


@dataclass(frozen=True)
class RobotsDecision:
    """One robots outcome, always citable (A10.4).

    `allowed` alone is not enough for an audit: a permissive parser and a correct one both
    return True, and only the cited rule distinguishes them.
    """

    allowed: bool
    directive: str | None          # "Allow", "Disallow", or None when no rule matched
    pattern: str | None
    group_user_agent: str | None   # which group decided, e.g. "*"
    rule: str                      # human-readable, e.g. "Disallow: /cgi-bin"
    source: str = "matched"        # matched | no_robots_txt | unfetchable | unparseable
    #: What the rule was actually compared against (A10.6, A17.3). A refusal that names a
    #: rule but not the URL it matched is a demonstration that could have been produced
    #: without reading the task, and one of ours was: it refused a fixed `Special:` page
    #: whatever the task asked for.
    evaluated_url: str | None = None
    evaluated_path: str | None = None
    evaluated_as: str | None = None   # our product token, as the group line sees it

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "directive": self.directive,
            "pattern": self.pattern,
            "group_user_agent": self.group_user_agent,
            "rule": self.rule,
            "source": self.source,
            "evaluated_url": self.evaluated_url,
            "evaluated_path": self.evaluated_path,
            "evaluated_as": self.evaluated_as,
        }


@dataclass
class RobotsEntry:
    rules: RobotsRules | None
    lines: list[str]
    fetched_at: float
    status: int | None
    note: str = ""


@dataclass
class RobotsCache:
    """Per-origin robots.txt with a TTL, so a run does not refetch it every step."""

    ttl_seconds: float = 3600.0
    _entries: dict[str, RobotsEntry] = field(default_factory=dict)

    def _fetch(self, origin: str) -> RobotsEntry:
        url = f"{origin}/robots.txt"
        req = urllib.request.Request(url, headers={
            "User-Agent": settings.user_agent,
            "Accept-Encoding": "gzip, deflate",
        })
        try:
            with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
                body = _decode(resp.read(), resp.headers.get("Content-Encoding"))
                text = body.decode("utf-8", "replace")
                rules = RobotsRules(text)
                if not rules.groups and _looks_like_markup(text):
                    # A captive portal or error page served with 200 parses to zero groups,
                    # which would read as "nothing is disallowed". That is under-blocking
                    # from a document that is not a policy at all (A10.3).
                    return RobotsEntry(None, text.splitlines(), time.time(), resp.status,
                                       "robots.txt returned HTTP 200 but the body is not a "
                                       "robots.txt (markup, no directives)")
                return RobotsEntry(rules, text.splitlines(), time.time(), resp.status)
        except urllib.error.HTTPError as exc:
            # 404 means no robots.txt, which permits everything (books.toscrape).
            note = ("no robots.txt (404): nothing is disallowed" if exc.code == 404
                    else f"robots.txt returned HTTP {exc.code}")
            return RobotsEntry(None, [], time.time(), exc.code, note)
        except Exception as exc:  # noqa: BLE001
            # Unreachable robots is not permission. Fail closed on the fetch, not open.
            return RobotsEntry(None, [], time.time(), None,
                               f"robots.txt could not be fetched: {type(exc).__name__}: {exc}")

    def _entry(self, origin: str) -> RobotsEntry:
        cached = self._entries.get(origin)
        if cached and (time.time() - cached.fetched_at) < self.ttl_seconds:
            return cached
        entry = self._fetch(origin)
        self._entries[origin] = entry
        return entry

    def decide(self, url: str, user_agent: str) -> RobotsDecision:
        """The robots outcome for one URL, with the rule that produced it (A10.3, A10.4).

        The boundary matters: **404 is a valid answer meaning "no restrictions"**, not a
        failure to fetch. `books.toscrape.com` serves no robots.txt, and treating that as
        unfetchable would lock out the whole site and take OP-6 and OP-7 with it. A network
        error, timeout, 5xx or unparseable body is a different thing entirely — the policy
        exists and we could not read it — and that fails closed.
        """
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        entry = self._entry(origin)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        evaluated = {"evaluated_url": url, "evaluated_path": path,
                     "evaluated_as": product_token(user_agent)}

        if entry.rules is None:
            if entry.status == 404:
                return RobotsDecision(
                    True, None, None, None,
                    "no robots.txt published (HTTP 404): the origin declares no restrictions",
                    source="no_robots_txt", **evaluated)
            return RobotsDecision(
                False, None, None, None,
                entry.note or "robots.txt could not be read; access is refused rather "
                              "than assumed",
                source="unparseable" if entry.status == 200 else "unfetchable",
                **evaluated)

        return replace(entry.rules.match(user_agent, path), **evaluated)

    async def allows(self, url: str, user_agent: str) -> tuple[bool, str | None]:
        """Backwards-compatible pair. Prefer `decide()`; the trace needs the full record."""
        d = self.decide(url, user_agent)
        return d.allowed, (None if d.source == "matched" and d.directive is None else d.rule)

    def describe(self) -> dict[str, Any]:
        return {
            "origins_cached": {
                origin: {"status": e.status, "lines": len(e.lines), "note": e.note}
                for origin, e in self._entries.items()
            },
            "policy": "robots.txt is binding, not advisory (S-2.3). A Disallowed path is "
                      "refused before navigation and the matching rule is reported.",
            "pacing": "Per-origin pacing is our own voluntary limit, not compliance with a "
                      "robots directive (A9.9).",
        }

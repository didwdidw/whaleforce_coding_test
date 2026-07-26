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
from dataclasses import dataclass, field
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


def _decode(raw: bytes, encoding: str | None) -> bytes:
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


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

    def _rules_for(self, user_agent: str) -> list[tuple[bool, str]]:
        """Most specific matching group, falling back to `*` (RFC 9309 §2.2.1)."""
        ua = user_agent.lower()
        best: list[tuple[bool, str]] | None = None
        best_len = -1
        star: list[tuple[bool, str]] | None = None
        for agents, rules in self.groups:
            for agent in agents:
                if agent == "*":
                    star = rules if star is None else star + rules
                elif agent and agent in ua and len(agent) > best_len:
                    best, best_len = rules, len(agent)
        if best is not None:
            return best
        return star or []

    @staticmethod
    def _to_regex(pattern: str) -> re.Pattern:
        out, anchored = [], pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        for ch in body:
            out.append(".*" if ch == "*" else re.escape(ch))
        return re.compile("^" + "".join(out) + ("$" if anchored else ""))

    def match(self, user_agent: str, path: str) -> tuple[bool, str | None]:
        """(allowed, the rule that decided it). Longest match wins; Allow wins ties."""
        decision: tuple[bool, str] | None = None
        best_len = -1
        for allow, pattern in self._rules_for(user_agent):
            if not self._to_regex(pattern).match(path):
                continue
            weight = len(pattern.rstrip("$"))
            if weight > best_len or (weight == best_len and allow):
                decision, best_len = (allow, pattern), weight
        if decision is None:
            return True, None
        allow, pattern = decision
        return allow, f"{'Allow' if allow else 'Disallow'}: {pattern}"


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
                return RobotsEntry(RobotsRules(text), text.splitlines(), time.time(),
                                   resp.status)
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

    async def allows(self, url: str, user_agent: str) -> tuple[bool, str | None]:
        """Return (allowed, matching rule). The rule is what the user is shown."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        entry = self._entry(origin)
        if entry.rules is None:
            # A 404 means the origin publishes no robots.txt, which disallows nothing.
            # Anything else — a network failure, a 5xx, a TLS error — is *not* permission.
            # Treating an unreadable robots.txt as "allowed" would let a transient failure
            # silently switch the policy off, which is the opposite of binding (S-2.3).
            if entry.status == 404:
                return True, None
            return False, (entry.note
                           or "robots.txt could not be read; access is refused rather "
                              "than assumed")
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        return entry.rules.match(user_agent, path)

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

"""Server-side HTTP fetcher — the one place non-browser retrieval happens (S-2.7, A10.5).

Policy is not a property of the browser tier. The robots defect found at M1 was on
`www.sec.gov`, which the browser never visits — the Task 2 seam reaches it through here.
So the egress guard and the robots decision are applied by this fetcher too, using the
same components, and every retrieval carries the rule that permitted it.

Two things the fetcher owns because they cannot be left to call sites:

**The declared User-Agent is set at construction** (A9.8). SEC returns 403 without one, and
that presents as a network-level block, so a per-call header is a per-call opportunity to
forget. The error path decompresses before reporting, because SEC's 403 body arrives
gzipped and reads as mojibake otherwise.

**Per-origin pacing** (S-2.15). SEC EDGAR is self-limited to 1 request/second against their
published cap of 10. This is our own voluntary limit, not compliance with a robots directive
(A9.9), and it is described that way wherever it surfaces.
"""

from __future__ import annotations

import gzip
import hashlib
import ssl
import threading
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app import egress
from app.config import settings
from app.robots import RobotsCache, RobotsDecision

#: Per-origin minimum seconds between requests. Ours, not theirs.
ORIGIN_PACING: dict[str, float] = {
    "www.sec.gov": 1.0,
    "data.sec.gov": 1.0,
}
DEFAULT_PACING = 0.25


class FetchRefused(Exception):
    """Refused before the request was made. Carries why, in reportable form."""

    def __init__(self, reason: str, *, failure_class: str, detail: dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.failure_class = failure_class
        self.detail = detail


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    body: bytes
    media_type: str | None
    retrieved_at: float
    sha256: str
    length: int
    robots: RobotsDecision
    egress_reason: str
    seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "media_type": self.media_type,
            "retrieved_at": self.retrieved_at,
            "sha256": self.sha256,
            "length": self.length,
            "seconds": round(self.seconds, 3),
            "robots": self.robots.to_dict(),
            "egress": self.egress_reason,
        }


def _ssl_context() -> ssl.SSLContext:
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


@dataclass
class ServerFetcher:
    robots: RobotsCache = field(default_factory=RobotsCache)
    user_agent: str = field(default_factory=lambda: settings.user_agent)
    max_bytes: int = 64 * 1024 * 1024
    _last_request: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _pace(self, host: str) -> float:
        """Sleep as needed so this origin is not hit faster than its own limit."""
        interval = ORIGIN_PACING.get(host, DEFAULT_PACING)
        with self._lock:
            last = self._last_request.get(host, 0.0)
            wait = max(0.0, last + interval - time.time())
            if wait:
                time.sleep(wait)
            self._last_request[host] = time.time()
        return wait

    def check(self, url: str) -> tuple[Any, RobotsDecision]:
        """Both policy decisions for a URL, without fetching. Same components the browser
        tier uses, so the two cannot drift apart."""
        return egress.check_url(url), self.robots.decide(url, self.user_agent)

    def fetch(self, url: str, *, accept: str = "*/*") -> FetchResult:
        """Retrieve bytes, or raise FetchRefused with the deciding rule attached."""
        eg, robots = self.check(url)
        if not eg.allowed:
            raise FetchRefused(f"Egress policy refused this URL: {eg.reason}",
                               failure_class="policy_refused",
                               detail={"egress": eg.to_dict(), "robots": robots.to_dict()})
        if not robots.allowed:
            raise FetchRefused(
                f"robots.txt disallows this path. Matched rule: `{robots.rule}` "
                f"(group `User-agent: {robots.group_user_agent or '?'}`).",
                failure_class="robots_disallowed",
                detail={"egress": eg.to_dict(), "robots": robots.to_dict()})

        host = urlsplit(url).hostname or ""
        self._pace(host)
        req = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": accept,
        })
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
                raw = resp.read(self.max_bytes + 1)
                if len(raw) > self.max_bytes:
                    # Silent truncation is prohibited by the seam contract; a cap that is
                    # hit is reported, never quietly applied.
                    raise FetchRefused(
                        f"Response exceeds the {self.max_bytes}-byte cap and was not "
                        f"retrieved. It is marked not-retrieved rather than truncated.",
                        failure_class="site_unavailable",
                        detail={"cap_bytes": self.max_bytes, "url": url})
                body = _decode(raw, resp.headers.get("Content-Encoding"))
                return FetchResult(
                    url=url, final_url=resp.geturl(), status=resp.status, body=body,
                    media_type=resp.headers.get("Content-Type"), retrieved_at=time.time(),
                    sha256=hashlib.sha256(body).hexdigest(), length=len(body),
                    robots=robots, egress_reason=eg.reason, seconds=time.time() - t0)
        except urllib.error.HTTPError as exc:
            # SEC's 403 for an undeclared User-Agent arrives gzipped; reading it raw
            # produces mojibake and hides the diagnosis (A9.8).
            detail = _decode(exc.read(), exc.headers.get("Content-Encoding"))
            raise FetchRefused(
                f"HTTP {exc.code} {exc.reason} from {host}",
                failure_class="site_unavailable",
                detail={"status": exc.code,
                        "body_head": detail[:300].decode("utf-8", "replace"),
                        "user_agent_declared": bool(self.user_agent)}) from exc
        except FetchRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            raise FetchRefused(f"{type(exc).__name__}: {exc}",
                               failure_class="site_unavailable",
                               detail={"url": url}) from exc

    def describe(self) -> dict[str, Any]:
        return {
            "user_agent": self.user_agent,
            "pacing_seconds_per_origin": {**ORIGIN_PACING, "*": DEFAULT_PACING},
            "pacing_note": ("Our own voluntary limit, not compliance with a robots "
                            "directive. SEC publishes a cap of 10 requests/second; we "
                            "self-limit an order of magnitude below it."),
            "policy": ("Egress guard and robots decision are applied here exactly as they "
                       "are for browser navigation, so the seam cannot reach an origin the "
                       "browser tier would be refused."),
            "max_bytes": self.max_bytes,
        }

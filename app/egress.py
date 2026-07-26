"""Deny-by-default egress policy (S-2.4 to S-2.8).

Every navigation and every intercepted subresource resolves its destination and has the
resolved address checked, on redirects as well as on the initial URL. Only https is
allowed; file:, data:, blob: and everything else are refused for navigation.

The fixture is reached over a public hostname precisely so no allow-list hole is needed
(S-2.8) — a carve-out for localhost would make the SSRF claim untrue. `ALLOW_PRIVATE_EGRESS`
exists for local development only and is reported by `describe()` so a run recorded with it
enabled is never mistaken for one made under production policy.

Residual risk: the gap between resolving a name and connecting to it. We check the
addresses a name resolves to at check time; a name that changes address in between could
still be connected to. This is disclosed rather than claimed solved (S-2.6).
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.config import settings

ALLOWED_SCHEMES = frozenset({"https", "http"})
#: http is permitted only for these hosts, and only because they demonstrably serve no
#: https. Every entry needs a reason, not a convenience.
HTTP_ALLOWED_HOSTS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class EgressDecision:
    allowed: bool
    url: str
    reason: str
    host: str | None = None
    resolved_ips: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "url": self.url,
            "reason": self.reason,
            "host": self.host,
            "resolved_ips": list(self.resolved_ips),
        }


def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Name the range an address falls in, or None if it is a routable public address."""
    if ip.is_loopback:
        return "loopback"
    # Checked before is_private, which also covers link-local — the cloud metadata
    # endpoint at 169.254.169.254 should be named as what it is in the trace.
    if ip.is_link_local:
        return "link-local"
    if ip.is_private:
        return "private (RFC1918 or equivalent)"
    if ip.is_multicast:
        return "multicast"
    if ip.is_reserved:
        return "reserved"
    if ip.is_unspecified:
        return "unspecified"
    # Carrier-grade NAT is neither private nor reserved by Python's classification.
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return "CGNAT (100.64.0.0/10)"
    # IPv4-mapped IPv6 would otherwise smuggle a private v4 address past the checks above.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return _is_blocked_address(ip.ipv4_mapped)
    return None


def check_url(url: str, *, allow_private: bool | None = None) -> EgressDecision:
    """Decide whether a URL may be requested. Applied per navigation and per redirect."""
    allow_private = (settings.allow_private_egress if allow_private is None else allow_private)
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()

    if scheme not in ALLOWED_SCHEMES:
        return EgressDecision(False, url, f"scheme '{scheme or 'none'}' is not permitted")
    host = parts.hostname
    if not host:
        return EgressDecision(False, url, "no host in URL")
    if scheme == "http" and host not in HTTP_ALLOWED_HOSTS and not allow_private:
        return EgressDecision(False, url, "http is only permitted for declared plaintext hosts",
                              host=host)

    # A bare address skips DNS but still gets range-checked.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = socket.getaddrinfo(host, parts.port or (443 if scheme == "https" else 80))
        except OSError as exc:
            return EgressDecision(False, url, f"DNS resolution failed: {exc}", host=host)
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
        if not addresses:
            return EgressDecision(False, url, "host resolved to no usable address", host=host)

    resolved = tuple(str(a) for a in addresses)
    if not allow_private:
        # Every resolved address must be public: one bad answer is enough to be routed to.
        for addr in addresses:
            blocked = _is_blocked_address(addr)
            if blocked:
                return EgressDecision(False, url,
                                      f"resolved address {addr} is {blocked}",
                                      host=host, resolved_ips=resolved)
    return EgressDecision(True, url, "allowed", host=host, resolved_ips=resolved)


def describe() -> dict:
    """The policy in force, for the trace and the UI."""
    return {
        "schemes_allowed": sorted(ALLOWED_SCHEMES),
        "http_allowed_hosts": sorted(HTTP_ALLOWED_HOSTS),
        "blocks": ["loopback", "private", "link-local", "CGNAT", "multicast", "reserved",
                   "IPv4-mapped IPv6 of any of the above"],
        "applied_to": ["navigation", "redirects", "intercepted subresource requests"],
        "private_egress_allowed": settings.allow_private_egress,
        "residual_risk": ("DNS rebinding: addresses are checked at resolve time and the "
                          "connection is not pinned to them (S-2.6)."),
    }

"""HTTPS for the measurement tools, and the distinction they were missing.

Both tools that measure a deployment from outside talk to it with `urllib`. On a machine
whose Python has no CA bundle wired up, every HTTPS request raises
`CERTIFICATE_VERIFY_FAILED` — and both tools caught that alongside "connection refused" and
recorded the same thing: the deployment did not answer.

That is the failure this project treats as the expensive kind. A broken client produced a
plausible reading about the server: a cold-start watcher that saw a continuous outage
through a healthy deployment, and a split whose every case would have been a suite error
naming the site. Nothing crashed and nothing looked wrong.

So two rules live here, in one place, for every tool that measures over HTTP:

  1. **Verify against a real trust store.** `certifi` ships in requirements; falling back to
     the platform default is fine, silently not verifying is not.
  2. **A client-side failure is not an observation about the server.** It stops the
     measurement and says what to fix. Only failures that are genuinely about the other end
     — refused, reset, timed out, DNS — are data.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover - certifi is in requirements
    certifi = None


class MeasurementBlocked(SystemExit):
    """The measuring machine cannot make requests. Not a result about the target."""


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where() if certifi else None)


def classify(exc: BaseException) -> None:
    """Raise if this exception is about us rather than about the deployment."""
    reason = getattr(exc, "reason", None)
    if isinstance(exc, ssl.SSLError) or isinstance(reason, ssl.SSLError):
        raise MeasurementBlocked(
            f"MEASUREMENT ABORTED: TLS failed on this machine, not on the deployment "
            f"({exc}).\nA certificate that cannot be verified here says nothing about "
            f"whether the service is up, and recording it as an outage would put a "
            f"fabricated number in the report.\nFix the trust store (certifi is in "
            f"requirements.txt) and measure again.")


def get_json(base: str, path: str, *, timeout: float = 5.0, user_agent: str,
             ) -> tuple[int | None, dict[str, Any]]:
    """Status and decoded body. `None` means the deployment did not answer."""
    request = urllib.request.Request(f"{base}{path}", headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=ssl_context()) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}
    except Exception as exc:  # noqa: BLE001 - classified, and only then treated as data
        classify(exc)
        return None, {}


def post_form(base: str, path: str, fields: dict[str, str], *, timeout: float = 30.0,
              user_agent: str) -> tuple[int | None, dict[str, Any]]:
    import urllib.parse

    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(f"{base}{path}", data=data,
                                     headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=ssl_context()) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}
    except Exception as exc:  # noqa: BLE001
        classify(exc)
        return None, {}

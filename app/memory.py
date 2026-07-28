"""Locator memory — the self-maintenance half of the two mechanisms (§8).

Deliberately small, and the boundaries are the design rather than the shortfall:

**It remembers only what a verified run proved.** A locator enters memory when the run that
used it ended `succeeded_verified` — not when the click worked. A click that worked on a run
whose answer nobody could re-resolve is exactly the locator we do not want to reuse.

**It is a hint, never an authority.** A remembered identity is re-resolved on the live page
like any other, and whatever it produces goes through the same verifier. Memory can save a
model call; it cannot make a claim true, and nothing here is ever read as a value.

**It cannot alter goal, tier, policy or budget.** The only thing a row can do is offer an
element to try. Page text feeds it (an accessible name is page text), so anything richer
would be a channel from a third-party page into our own control flow.

**It quarantines rather than degrades.** Three consecutive failures and the row stops being
offered, with the reason recorded. A locator that has stopped working is worse than no
locator: it spends a step and a diagnosis before the run gets to where it would have started
without it.

The key is `(origin, operation, role)`. Origin rather than URL because a listing and its page
two are the same site and the same control; role rather than selector because a selector is
our spelling of an element and the role is the page's.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

#: How long a confirmation is worth anything. A site redesign is not announced, so a row
#: nobody has re-confirmed inside this window is treated as stale rather than as a fact.
TTL_SECONDS = 14 * 24 * 3600
#: Consecutive failures before a row is quarantined. Three rather than one: a page that was
#: mid-render, or a run that failed before it got near the element, is not evidence about
#: the locator.
QUARANTINE_AFTER = 3


@dataclass(frozen=True)
class Remembered:
    origin: str
    operation: str
    role: str
    identity: dict[str, Any]
    confirmed_at: float
    uses: int
    hits: int
    heals: int
    consecutive_failures: int

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.confirmed_at)

    @property
    def stale(self) -> bool:
        return self.age_seconds > TTL_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {"origin": self.origin, "operation": self.operation, "role": self.role,
                "identity": self.identity, "confirmed_at": self.confirmed_at,
                "age_seconds": round(self.age_seconds, 1), "stale": self.stale,
                "uses": self.uses, "hits": self.hits, "heals": self.heals,
                "consecutive_failures": self.consecutive_failures}


class LocatorMemory:
    """The store's locator table, with the rules above enforced here rather than by callers."""

    def __init__(self, store) -> None:
        self._store = store

    # ---- reading -----------------------------------------------------------------

    def recall(self, origin: str, operation: str, role: str) -> Remembered | None:
        """The identity that last worked here, or None — including for a quarantined or
        stale row, which are absences with a reason rather than rows to be filtered by the
        caller."""
        row = self._store.locator_row(origin, operation, role)
        if row is None or row["quarantined_at"]:
            return None
        remembered = _from_row(row)
        return None if remembered.stale else remembered

    def why_not(self, origin: str, operation: str, role: str) -> str:
        """Why `recall` returned nothing, for the trace. An absence that says nothing looks
        the same whether memory is empty, expired or quarantined, and those are three
        different facts about the system (A11.8)."""
        row = self._store.locator_row(origin, operation, role)
        if row is None:
            return "nothing remembered for this origin, operation and role"
        if row["quarantined_at"]:
            return f"quarantined: {row['quarantine_reason']}"
        if _from_row(row).stale:
            return (f"last confirmed {round((time.time() - row['confirmed_at']) / 86400, 1)} "
                    f"days ago, past the {TTL_SECONDS // 86400}-day confirmation window")
        return ""

    # ---- writing -----------------------------------------------------------------

    def remember(self, *, origin: str, operation: str, role: str,
                 identity: dict[str, Any], run_id: str, healed: bool = False) -> None:
        """Write back what a `succeeded_verified` run proved. Callers do not decide this —
        `record_run` does, from the run's terminal status."""
        self._store.locator_write(origin=origin, operation=operation, role=role,
                                  identity=identity, run_id=run_id, healed=healed)

    def used(self, origin: str, operation: str, role: str, *, worked: bool) -> None:
        """One attempt to use a remembered locator. Three consecutive failures quarantine
        the row; any success clears the count, because a locator that works is not on a
        countdown."""
        self._store.locator_outcome(origin, operation, role, worked=worked,
                                    quarantine_after=QUARANTINE_AFTER)

    # ---- reporting ---------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """What /healthz reports. Counters, not a rate: a hit rate over a handful of rows
        reads as a measurement and is not one."""
        return {**self._store.locator_stats(),
                "ttl_days": TTL_SECONDS // 86400,
                "quarantine_after_consecutive_failures": QUARANTINE_AFTER,
                "written_from": "succeeded_verified runs only",
                "authority": ("a hint that is re-resolved and re-verified like any other "
                              "locator; it can save a model call and cannot make a claim")}


def _from_row(row) -> Remembered:
    return Remembered(origin=row["origin"], operation=row["operation"], role=row["role"],
                      identity=json.loads(row["identity"]),
                      confirmed_at=float(row["confirmed_at"]), uses=int(row["uses"]),
                      hits=int(row["hits"]), heals=int(row["heals"]),
                      consecutive_failures=int(row["consecutive_failures"]))

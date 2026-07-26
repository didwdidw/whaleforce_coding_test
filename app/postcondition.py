"""Postconditions, frozen and hashed at plan time (S-4.12).

A postcondition is written **before** execution and never after. That ordering is the whole
mechanism: it is what makes "recovery may not lower the bar" checkable instead of a promise,
and it is what stops a run from grading itself against whatever it happened to find.

Two things are frozen that might look like implementation detail and are not:

**The inputs.** A search postcondition freezes the term the task named. Verification later
re-reads the term the *page* echoed back and compares. A run that searched for something
subtly different than what was asked answers a different question, and the page it produces
is a perfectly valid page — so nothing except this comparison can catch it.

**The anchors.** The label text and structural relation a claim will be verified through are
chosen at plan time, before the answer is known. Choosing an anchor after seeing the value is
how a verifier ends up confirming whatever the executor already believed.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

#: Bumped when the serialised shape changes, so old hashes are not silently comparable.
SPEC_VERSION = "pc/1"


class Relation(str, enum.Enum):
    """How a value is bound to its label (S-4.9). Shape checks alone are not a relation."""

    #: Label in a header cell, value in the data cell of the same row.
    TABLE_ROW_CELL = "table_row_cell"
    #: A counter sentence that restates the query it answered: `N results for "term"`.
    COUNTER_ECHO = "counter_echo"
    #: The empty-state element XB-1 Mode A rests on.
    EMPTY_STATE = "empty_state"
    #: `Page N of M · K products` — also the coverage anchor for Mode B.
    PAGER_POSITION = "pager_position"
    #: Every member of a list, within a declared container.
    LIST_ENUMERATION = "list_enumeration"
    #: An element that must be absent from the artifact — evidence of a state transition.
    ELEMENT_ABSENT = "element_absent"


class AbsenceMode(str, enum.Enum):
    """Which proof of absence this plan is entitled to attempt (Amendment 3)."""

    NONE = "none"
    A_EMPTY_STATE = "A"
    B_ENUMERATION = "B"


@dataclass(frozen=True)
class RequiredAction:
    """An action the case declares as necessary (S-4.2). The verifier checks the trace shows
    it happened; it does not claim the action was impossible to bypass (S-4.3)."""

    kind: str
    target: str
    why: str
    times: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "target": self.target, "why": self.why,
                "times": self.times}


@dataclass(frozen=True)
class ClaimSpec:
    name: str
    label: str
    relation: Relation
    value_type: str
    container: str = ""
    #: Set when a claim is allowed to be missing without failing the whole run — used for
    #: the parts of a page a mutation is expected to move.
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "relation": self.relation.value,
                "value_type": self.value_type, "container": self.container,
                "optional": self.optional}


@dataclass(frozen=True)
class Postcondition:
    goal: str
    operation: str
    target_url: str
    inputs: dict[str, Any] = field(default_factory=dict)
    required_actions: tuple[RequiredAction, ...] = ()
    claims: tuple[ClaimSpec, ...] = ()
    absence: AbsenceMode = AbsenceMode.NONE
    #: Required before Mode B may conclude anything (A3.2).
    coverage_anchor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": SPEC_VERSION,
            "goal": self.goal,
            "operation": self.operation,
            "target_url": self.target_url,
            "inputs": self.inputs,
            "required_actions": [a.to_dict() for a in self.required_actions],
            "claims": [c.to_dict() for c in self.claims],
            "absence": self.absence.value,
            "coverage_anchor": self.coverage_anchor,
        }

    @property
    def sha256(self) -> str:
        return digest(self.to_dict())


def canonical(data: dict[str, Any]) -> str:
    """One serialisation, used by both the freeze and the re-check. Two functions that
    happen to agree today are a hash comparison waiting to become meaningless."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(data).encode("utf-8")).hexdigest()


def matches_frozen(stored: dict[str, Any] | None, stored_hash: str | None) -> bool:
    """Whether the stored postcondition still hashes to what was recorded at plan time.

    Divergence is itself a failure (S-4.12) — it means the object verification ran against
    is not the object the run committed to.
    """
    if stored is None or not stored_hash:
        return False
    return digest(stored) == stored_hash

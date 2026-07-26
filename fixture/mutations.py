"""Mutation catalogue MU-1 … MU-9 (S-9.2).

Every mutation is a **markup transform**. None of them touches `fixture/catalogue.py`,
which is where answers come from, so a mutation can break a locator but can never change
the correct result. `catalogue.selftest()` asserts this.

Seeds are recorded with every run (S-9.4), so any result is reproducible from the seed.
M1 wires the seed through end to end and implements the transforms that need no page
support; the remainder land with the mutation gate suite at M5, and each is marked with
its status here rather than silently absent.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

#: Named seeds. `none` is the unmutated control every comparison is made against.
SEEDS: tuple[str, ...] = (
    "none", "mu1-idclass", "mu2-text", "mu3-wrap", "mu4-decoys",
    "mu5-delay", "mu6-overlay", "mu7-move-pager", "mu8-empty", "mu9-malformed",
)

MUTATIONS: dict[str, dict[str, Any]] = {
    "none":            {"id": "MU-0", "desc": "control, unmutated",            "implemented": True},
    "mu1-idclass":     {"id": "MU-1", "desc": "rename all id/class attributes", "implemented": True},
    "mu2-text":        {"id": "MU-2", "desc": "change button and label text",   "implemented": True},
    "mu3-wrap":        {"id": "MU-3", "desc": "insert wrappers / reorder DOM",  "implemented": True},
    "mu4-decoys":      {"id": "MU-4", "desc": "two near-identical decoys",      "implemented": False},
    "mu5-delay":       {"id": "MU-5", "desc": "delayed rendering of target",    "implemented": False},
    "mu6-overlay":     {"id": "MU-6", "desc": "overlay covering the action",    "implemented": False},
    "mu7-move-pager":  {"id": "MU-7", "desc": "move the pagination control",    "implemented": False},
    "mu8-empty":       {"id": "MU-8", "desc": "empty state (drives XB-1)",      "implemented": False},
    "mu9-malformed":   {"id": "MU-9", "desc": "malformed / broken markup",      "implemented": False},
}

#: Attribute values the mutation layer must not rename: they are the fixture's own test
#: scaffolding, not part of the surface under test.
PROTECTED = ("data-testhook",)


def _stable_rename(value: str, seed: str) -> str:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()[:8]
    return f"m{digest}"


def apply_mutations(markup: str, seed: str) -> str:
    """Transform markup for a seed. Returns the input unchanged for unknown seeds."""
    if seed in ("none", "", None) or seed not in MUTATIONS:
        return markup
    if not MUTATIONS[seed]["implemented"]:
        return markup

    if seed == "mu1-idclass":
        def rename(m: re.Match) -> str:
            attr, quote, value = m.group(1), m.group(2), m.group(3)
            if any(p in m.group(0) for p in PROTECTED):
                return m.group(0)
            renamed = " ".join(_stable_rename(v, seed) for v in value.split())
            return f'{attr}={quote}{renamed}{quote}'
        return re.sub(r'\b(id|class)=(["\'])([^"\']*)\2', rename, markup)

    if seed == "mu2-text":
        swaps = {">Search<": ">Find<", ">Next<": ">Forward<", ">Previous<": ">Back<",
                 ">Dismiss<": ">Close<", "Product code": "Item reference"}
        for a, b in swaps.items():
            markup = markup.replace(a, b)
        return markup

    if seed == "mu3-wrap":
        # Wrap every result row so structural paths that assume a direct parent break.
        return markup.replace('<li class="result"', '<li class="result-wrapper"><span><li class="result"') \
                     .replace("</li><!--/result-->", "</li></span></li><!--/result-->")

    return markup


def describe(seed: str) -> dict[str, Any]:
    info = MUTATIONS.get(seed, {"id": "unknown", "desc": "unknown seed", "implemented": False})
    return {"seed": seed, **info}


def catalogue() -> list[dict[str, Any]]:
    return [{"seed": s, **MUTATIONS[s]} for s in SEEDS]

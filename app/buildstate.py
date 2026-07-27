"""What this build can actually do, derived rather than described (A13.3).

A sentence about the state of the build is a claim, and a stale claim is a false one. The
support page said four operations were "not yet implemented" for a milestone after they
shipped, and the submit form said out-of-surface tasks were attempted when they were
refused before any browsing. Nothing was lying on purpose; prose simply has no reason to
change when code does.

So the flags below are read off the code that would have to exist for the claim to be true,
and the templates render from them. **The limit is honest and worth stating: this proves a
path exists, not that it works.** What proves it works is the eval harness (A13.5); what
this prevents is the page claiming a path that is not even there.
"""

from __future__ import annotations

from typing import Any

MILESTONE = "M4"


def gate_operations() -> list[dict[str, Any]]:
    """GS-1/GS-2/GS-3 with whether this build can reach each one (A14.7).

    Published as mechanism evidence and nothing else: they are on a site we wrote, so a
    reliability figure measured on them would be us marking our own exam (A1.3). What is
    worth showing is the construction — why the UI action cannot be skipped — which is a
    property of the fixture's markup rather than of our success rate.
    """
    from app.executor import GATE_OPERATIONS, Executor

    routes = dict(Executor.ROUTES)
    return [{"id": g.id, "mechanism": g.mechanism,
             "shortcut_proof_because": g.shortcut_proof_because,
             "reachable": g.route in routes}
            for g in GATE_OPERATIONS]


def mutation_catalogue() -> list[dict[str, Any]]:
    """The fixture's own mutation catalogue (S-9.2), with the wired/not-wired flag it
    declares. Read from the fixture rather than restated, so a page cannot advertise a
    mutation the fixture does not apply."""
    from fixture.mutations import catalogue

    return [m for m in catalogue() if m["seed"] != "none"]


def state() -> dict[str, Any]:
    from app.config import settings
    from app.executor import PROMISED_RECORDS, Executor

    routes = dict(Executor.ROUTES)
    mutations = mutation_catalogue()
    return {
        "milestone": MILESTONE,
        "promised_records": len(PROMISED_RECORDS),
        "records_reachable": sum(1 for r in PROMISED_RECORDS if r.route in routes),
        "mutations_declared": len(mutations),
        "mutations_wired": sum(1 for m in mutations if m["implemented"]),
        # The generic loop is what lets an unrouted task be attempted at all (A13.2).
        "generic_loop": hasattr(Executor, "_plan_generic"),
        # Whether a plain-language task on a real site is planned by the model (A13.4).
        "planner_is_default": settings.planner_default_on_real_sites,
        "model_id": settings.provider.model_id,
        "locator_memory": hasattr(Executor, "_locator_memory"),
    }

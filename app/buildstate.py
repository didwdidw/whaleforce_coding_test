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


def state() -> dict[str, Any]:
    from app.config import settings
    from app.executor import PROMISED_RECORDS, Executor

    routes = dict(Executor.ROUTES)
    return {
        "milestone": MILESTONE,
        "promised_records": len(PROMISED_RECORDS),
        "records_reachable": sum(1 for r in PROMISED_RECORDS if r.route in routes),
        # The generic loop is what lets an unrouted task be attempted at all (A13.2).
        "generic_loop": hasattr(Executor, "_plan_generic"),
        # Whether a plain-language task on a real site is planned by the model (A13.4).
        "planner_is_default": settings.planner_default_on_real_sites,
        "model_id": settings.provider.model_id,
        "locator_memory": hasattr(Executor, "_locator_memory"),
    }

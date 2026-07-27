"""Is the reducer's site-specific chrome list an optimisation, or is it producing our answers?

The reducer excludes site chrome from the element budget, and its exclusion list names
MediaWiki selectors directly: `#mw-panel`, `.vector-header`, `#vector-toc` and so on. Named
strings for one site sitting in a general component is the shape of a special case, and a
special case that makes a case pass is passing the gate by weakening it.

Talking about where the line is does not settle it. This does: **take the site-specific
strings out, put a generic chrome exclusion in their place, and run OP-4 again.**

- Still passes, only slower or noisier → optimisation. Keep it.
- Fails → those strings were producing the answer. That is a special case, and a design
  conversation rather than a commit.

Both arms run the same frozen postcondition through the same verifier. Only the exclusion
list differs.

Usage:  python -m preflight.chrome_selectors_ab
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import tempfile
import time

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("REQUIRE_PERSISTENT_STORE", "false")

from app import reduce as reduce_module                                    # noqa: E402
from app.browser import BrowserSupervisor                                  # noqa: E402
from app.executor import Executor                                          # noqa: E402
from app.models import Run, new_id                                         # noqa: E402
from app.store import Store                                                # noqa: E402

OUT = pathlib.Path(__file__).parent.parent / "docs" / "m4-chrome-selectors-ab.json"

TASK = ("Sort the constituents table by GICS Sector descending and read the top row, "
        "use the planner")

#: What the reducer ships with: standards-based landmarks plus named MediaWiki containers.
SHIPPED = reduce_module.REDUCE_JS

#: The same reducer with every site-specific selector removed, leaving only what any page
#: on the web publishes about its own chrome: HTML5 sectioning elements and ARIA landmarks.
GENERIC_CHROME = ("nav, header, footer, [role=\"navigation\"], [role=\"banner\"],"
                  "[role=\"contentinfo\"], [role=\"complementary\"], [role=\"search\"]")


def _generic_arm() -> str:
    start = SHIPPED.index("const CHROME =")
    end = SHIPPED.index(";", SHIPPED.index(".sitenav"))
    return SHIPPED[:start] + f"const CHROME = '{GENERIC_CHROME}'" + SHIPPED[end:]


async def _one_arm(label: str, reduce_js: str) -> dict:
    reduce_module.REDUCE_JS = reduce_js
    tmp = pathlib.Path(tempfile.mkdtemp())
    store = Store(tmp / "runs.sqlite3", tmp / "artifacts")
    supervisor = BrowserSupervisor()
    await supervisor.start()
    try:
        executor = Executor(supervisor, store)
        run = Run(id=new_id("run"), task=TASK, tier=executor.classify(TASK)[0])
        store.save_run(run)
        started = time.time()
        await executor.execute(run)
        reductions = [t.detail["reduction"] for t in run.trace
                      if isinstance(t.detail.get("reduction"), dict)]
        return {
            "arm": label,
            "terminal_status": run.terminal_status.value if run.terminal_status else None,
            "failure_class": run.failure_class.value if run.failure_class else None,
            "counts_as_success": run.counts_as_success,
            "seconds": round(time.time() - started, 1),
            "model_calls": (run.budget.llm_calls_exploration
                            + run.budget.llm_calls_recovery),
            "input_tokens": run.budget.input_tokens,
            "output_tokens": run.budget.output_tokens,
            "usd": round(run.budget.usd, 5),
            "steps": run.budget.steps,
            "kept_interactive": [r["kept"]["interactive"] for r in reductions],
            "dropped_chrome": [r["dropped"].get("interactive_chrome_over_cap", 0)
                               for r in reductions],
            "dropped_over_cap": [r["dropped"].get("interactive_over_cap", 0)
                                 for r in reductions],
            "explanation": run.explanation[:300],
        }
    finally:
        await supervisor.aclose()
        reduce_module.REDUCE_JS = SHIPPED


async def _views() -> dict:
    """What each arm actually shows the model, measured without spending a model call.

    The run outcome is the criterion, but it is a coarse instrument: a provider hiccup looks
    the same as a reduction failure. This says directly how much the two exclusion lists
    disagree about the page.
    """
    from app.reduce import reduce_page

    supervisor = BrowserSupervisor()
    await supervisor.start()
    out = {}
    try:
        async with supervisor.context() as (context, _generation):
            page = await context.new_page()
            await page.goto(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                wait_until="load")
            await page.wait_for_selector("#constituents th.headerSort", timeout=15_000)
            for label, js in (("shipped", SHIPPED), ("generic", _generic_arm())):
                reduce_module.REDUCE_JS = js
                view = await reduce_page(page, ("GICS Sector", "Symbol", "Security",
                                                "constituents"))
                out[label] = {
                    "kept": len(view["interactive"]),
                    "dropped": view["dropped"],
                    "prompt_chars": len(json.dumps(view, separators=(",", ":"))),
                    "names": [e.get("text") or e.get("label") or ""
                              for e in view["interactive"]],
                }
    finally:
        await supervisor.aclose()
        reduce_module.REDUCE_JS = SHIPPED

    shipped, generic = set(out["shipped"]["names"]), set(out["generic"]["names"])
    out["difference"] = {
        "only_in_shipped": sorted(shipped - generic)[:20],
        "only_in_generic": sorted(generic - shipped)[:20],
        "overlap": len(shipped & generic),
        "sort_header_present_in_shipped": "GICS Sector" in shipped,
        "sort_header_present_in_generic": "GICS Sector" in generic,
    }
    return out


async def main() -> None:
    views = await _views()
    print("view comparison (no model calls):")
    for arm in ("shipped", "generic"):
        print(f"  {arm:9} kept {views[arm]['kept']:3}  "
              f"{views[arm]['prompt_chars']:6} chars")
    print(f"  overlap {views['difference']['overlap']}, "
          f"sort header present: shipped="
          f"{views['difference']['sort_header_present_in_shipped']} "
          f"generic={views['difference']['sort_header_present_in_generic']}\n")

    arms = []
    for label, js in (("shipped (site-specific chrome list)", SHIPPED),
                      ("generic (landmarks and sectioning elements only)", _generic_arm())):
        result = await _one_arm(label, js)
        # A provider fault is not evidence about reduction. Retry once rather than let an
        # unrelated 503 be recorded as a verdict about our own code.
        if result["failure_class"] in ("provider_error", "provider_quota"):
            print(f"    (provider fault on '{label}', retrying once)")
            await asyncio.sleep(20)
            result = await _one_arm(label, js)
        arms.append(result)
        print(f"{result['terminal_status']:20} {label}")
        print(f"    {result['model_calls']} calls, {result['input_tokens']} in, "
              f"{result['seconds']}s, ${result['usd']}, "
              f"kept {result['kept_interactive']}")

    provider_fault = [a for a in arms
                      if a["failure_class"] in ("provider_error", "provider_quota")]
    passed = [a for a in arms if a["counts_as_success"]]
    if provider_fault:
        verdict = ("inconclusive — an arm failed on a provider fault, which says nothing "
                   "about reduction")
    elif len(passed) == 2:
        verdict = "optimisation — the generic arm reaches the same verified answer"
    elif arms[0]["counts_as_success"]:
        verdict = "SPECIAL CASE — the site-specific strings are load-bearing"
    else:
        verdict = "inconclusive — the shipped arm did not pass either, so nothing is isolated"
    print(f"\nverdict: {verdict}")

    OUT.write_text(json.dumps({
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
        "question": ("Do the reducer's MediaWiki-specific chrome selectors produce OP-4's "
                     "answer, or only make reaching it cheaper?"),
        "criterion": ("Replace them with generic chrome exclusion and re-run OP-4. Passing "
                      "more slowly is an optimisation; failing means they were producing "
                      "the answer."),
        "generic_chrome_selector": GENERIC_CHROME,
        "verdict": verdict,
        "views": views,
        "arms": arms,
    }, indent=1), encoding="utf-8")
    print(f"written {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

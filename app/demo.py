"""The task chips offered on the home page, and the subset run at startup.

Split by intent rather than kept as one list, because the intent is what the admission
corpus needs to assert against and a comment cannot be asserted against.

The two lists are not the same list, deliberately. **Pre-executed** runs happen on every
boot, so they stay on the fixture and on the deterministic path: they are what a visitor
can inspect when the provider quota is spent, and paying model calls to regenerate them at
each restart would spend exactly the quota that keeps them working. **Chips** additionally
offer the promised records in plain language — those execute live, model-driven, which is
the mechanism being graded and the one a reviewer should be able to trigger without knowing
any special phrasing.
"""

from __future__ import annotations

#: Fixture demonstrations. One of each outcome — a verified answer, a proven absence, a
#: right answer scored as a failure for skipping a declared action, and a run whose control
#: is relabelled under it by a mutation seed, so it has to recover within the attempt. None
#: of them need a provider, and none of them is healed across runs: nothing is remembered
#: between runs in this build, and describing one of these as healed said otherwise.
PRE_EXECUTED_ACCEPTED: tuple[str, ...] = (
    "Search the fixture catalogue for lantern",
    "Is any product in the fixture catalogue priced over £100?",
    "Read page 2 of the fixture browse listing without clicking next",
    "Dismiss the overlay on the fixture gated page and read the reference code, seed mu2-text",
)

#: The chip that exists to show what a refusal looks like.
DEMO_REFUSED: tuple[str, ...] = (
    "Log into my brokerage account and tell me my balance",
)

#: The promised records, phrased as a person would phrase them. Not pre-executed: each one
#: is a live model-driven run on a real site.
PROMISED_TASKS: tuple[str, ...] = (
    "On the Wikipedia list of S&P 500 companies, sort the constituents table by GICS "
    "Sector descending and tell me the top row",
    # Names its own article. "That article" read as a follow-on from the chip above it and
    # resolved to nothing, so the one button offering OP-5 could not reach OP-5: it refused
    # for having no entry point, on the record Amendment 28 is about.
    "On the Wikipedia article for Apple Inc., expand the first collapsed box and tell me "
    "its Hardware group",
    "Go to the nonfiction category listing on books.toscrape.com and read the second page "
    "of results",
    "Open the product detail page for A Light in the Attic and read its labelled product "
    "information",
)

PRE_EXECUTED: tuple[str, ...] = PRE_EXECUTED_ACCEPTED + DEMO_REFUSED

#: Everything the home page offers. Admission must accept all of it but the refusal chip.
DEMO_ACCEPTED: tuple[str, ...] = PROMISED_TASKS + PRE_EXECUTED_ACCEPTED
CHIPS: tuple[str, ...] = DEMO_ACCEPTED + DEMO_REFUSED

#: What the input box suggests. A promised record in plain language, so the first thing a
#: reviewer sees offered is the surface the system actually promises.
PLACEHOLDER = PROMISED_TASKS[3]

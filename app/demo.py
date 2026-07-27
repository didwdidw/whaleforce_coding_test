"""The task chips offered on the home page.

Split by intent rather than kept as one list, because the intent is what the admission
corpus needs to assert against and a comment cannot be asserted against. Four of these are
demonstrations of the working surface and must be admitted; the fifth exists to show what a
refusal looks like and must be refused.
"""

from __future__ import annotations

DEMO_ACCEPTED: tuple[str, ...] = (
    "Search the fixture catalogue for lantern",
    "Is any product priced over £100?",
    "Read page 2 of the browse listing without clicking next",
    "Dismiss the overlay on the gated page and read the reference code, seed mu2-text",
)

DEMO_REFUSED: tuple[str, ...] = (
    "Log into my brokerage account and tell me my balance",
)

DEMO_TASKS: tuple[str, ...] = DEMO_ACCEPTED + DEMO_REFUSED

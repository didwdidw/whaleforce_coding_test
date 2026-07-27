"""Controls that fail closed, tested in both directions.

We already knew one half of this: a control whose failure mode is *closed* ends up closed,
because nothing complains when it refuses. This is the mirror image, and it is worse. A
control that is **always on and judging wrongly** is indistinguishable from one that is on
and judging correctly — both produce refusals, refusals look like caution, and nobody files a
bug against caution.

Two of them were found that way. `_same_page` compared URL paths without decoding
percent-escapes, so `List_of_S%26P_500_companies` and `List_of_S&P_500_companies` were two
different pages and correct runs were rejected. The out-of-scope classifier matched nouns
rather than acts, so `order` refused "sort in descending order" and `book a` refused "read
the product page for the book A Light in the Attic" — our own OP-7 case, phrased the way a
person would phrase it. Both were live. Neither had ever produced a complaint.

The property that makes a fail-closed control checkable is a corpus with **both halves**:
what it must refuse, and what it must not. A test that only asserts the refusals passes just
as happily when the control refuses everything.
"""

from __future__ import annotations

import pytest

from app.executor import Executor
from app.models import Tier
from app.verifier import _same_page

WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


@pytest.fixture()
def classify():
    return Executor.__new__(Executor).classify


# --- admission: what the system will not attempt ----------------------------------

#: Read-only tasks. Every one of these is inside the promised surface, and several are our
#: own dev cases written the way a person would write them.
MUST_BE_ACCEPTED = [
    "Sort the constituents table by GICS Sector in descending order and read the top row",
    "List the S&P 500 companies in alphabetical order",
    "Read the product page for the book A Light in the Attic",
    "Report the order of the first five rows",
    "Which companies were added to the index most recently?",
    "Read the customer comments on the notes page",
    "Find the cheapest book and report its price",
    "Show me the post office branches listed on the page",
    "What is the account balance column header called?",
    "Reserve judgement on the first row",
    "Expand the collapsed navbox and report the Energy group",
    "Go to the second page of results and list the titles",
]

#: Tasks that ask the agent to authenticate, transact, or write to somebody else's system.
MUST_BE_REFUSED = [
    ("Log in to my account and read the balance", "authentication"),
    ("Sign up for the newsletter", "authentication"),
    ("Buy the cheapest book", "transaction"),
    ("Add it to the basket and check out", "transaction"),
    ("Book a table for two on the restaurant page", "transaction"),
    ("Place an order for the top item", "transaction"),
    ("Pay for the item in the basket", "transaction"),
    ("Subscribe to the mailing list", "transaction"),
    ("Submit a review for this product", "writing"),
    ("Leave a comment on the article", "writing"),
    ("Delete the first row", "writing"),
    ("Send an email to the seller", "writing"),
    ("Read my inbox", "personal"),
    ("Solve the captcha and continue", "anti-bot"),
]


@pytest.mark.parametrize("task", MUST_BE_ACCEPTED)
def test_a_read_only_task_is_not_refused_for_containing_a_transactional_word(task, classify):
    """The half that was missing. A control with only refusal tests passes while refusing
    everything, which is exactly the state this one was in."""
    tier, reason = classify(task)
    assert tier is not Tier.REFUSED, (
        f"refused as {reason!r}: {task!r}. The task asks the system to read something; "
        f"matching a noun rather than an act turns caution into a wrong answer that nobody "
        f"reports, because a refusal never looks like a bug.")


@pytest.mark.parametrize("task,kind", MUST_BE_REFUSED)
def test_a_task_that_asks_for_an_action_we_do_not_take_is_refused(task, kind, classify):
    tier, reason = classify(task)
    assert tier is Tier.REFUSED, f"{kind}: {task!r} was admitted"
    assert reason


def test_the_refusal_corpus_covers_every_declared_reason(classify):
    """A reason nothing exercises is a rule nothing checks."""
    from app.executor import OUT_OF_SCOPE

    declared = {reason for _pattern, reason in OUT_OF_SCOPE}
    exercised = {classify(task)[1] for task, _kind in MUST_BE_REFUSED}
    assert declared == exercised, f"never exercised: {declared - exercised}"


# --- the same-page guard ----------------------------------------------------------

def test_the_same_page_guard_accepts_one_page_written_two_ways():
    assert _same_page("https://en.wikipedia.org/wiki/List_of_S&P_500_companies", WIKI)
    assert _same_page(WIKI + "?action=raw", WIKI)
    assert _same_page(WIKI + "/", WIKI)


def test_the_same_page_guard_still_rejects_a_different_page():
    """The refusals have to keep working, or the fix has only moved the failure."""
    assert not _same_page("https://en.wikipedia.org/wiki/S%26P_500", WIKI)
    assert not _same_page("https://en.m.wikipedia.org/wiki/List_of_S%26P_500_companies",
                          WIKI)
    assert not _same_page("http://en.wikipedia.org/wiki/List_of_S%26P_500_companies", WIKI)
    assert not _same_page(None, WIKI)


# --- routing -----------------------------------------------------------------------

def test_every_promised_operation_is_reachable_by_the_task_that_describes_it():
    """Routing abstains when a task matches no operation or more than one, which is right —
    and is also a way for an operation to become unreachable without anything saying so."""
    executor = Executor.__new__(Executor)
    for task, expected in (
        ("Sort the constituents table by GICS Sector descending and read the top row",
         "wiki_sort"),
        ("Expand the collapsed navbox and read the Energy group", "wiki_expand"),
        ("Go to the nonfiction category listing and read the second page of results",
         "book_category"),
        ("Open the product detail page and read its labelled product information",
         "book_detail"),
    ):
        operation, candidates, hits = executor.route(task)
        assert operation == expected, (
            f"{task!r} routed to {operation!r} (candidates {candidates}, markers {hits})")

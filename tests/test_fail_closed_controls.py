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

**Where the corpus comes from matters as much as that it exists.** The first version of the
must-accept list was written in the same sitting as the fix, by whoever had just decided what
the rule should be — the same shape as an inventory written from memory, and it carries the
same assumptions it is meant to audit. So it is gone. The must-accept corpus is now every
task in `eval/dev-set.md`, verbatim, plus the chips on the home page: sentences written for
other purposes, before this rule existed, which is exactly why they can contradict it.

The must-refuse half is still ours, and that asymmetry is deliberate rather than overlooked:
nothing outside this repo enumerates acts we decline. Its guard is structural instead —
every declared refusal reason must be exercised by some case, so a rule can neither be added
without a case nor kept after nothing reaches it.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from lxml import html as lxml_html

from app.demo import DEMO_ACCEPTED, DEMO_REFUSED
from app.executor import Executor
from app.models import Tier
from app.postcondition import (
    AbsenceMode, ClaimSpec, Postcondition, Relation, RequiredAction, digest, matches_frozen,
)
from app.verifier import _same_page

REPO = pathlib.Path(__file__).parent.parent
WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


@pytest.fixture()
def classify():
    return Executor.__new__(Executor).classify


# --- admission: a corpus this session did not write -------------------------------

def _dev_cases() -> list[tuple[str, str, bool]]:
    """Every case in the dev split as (id, task, must-be-refused).

    The expectation is read from the case's own `expected_terminal_status`, not restated
    here: `policy_refused` is the admission check's refusal and nothing else is. DEV-13 is
    the reason that distinction is load-bearing — it is refused, but by robots.txt after
    admission, so admission must let it through.
    """
    text = (REPO / "eval" / "dev-set.md").read_text(encoding="utf-8")
    cases = []
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        task = re.search(r'^- \*\*task\*\*\s+"(.+?)"\s*$', block, re.M)
        expected = re.search(r"^- \*\*expected_terminal_status\*\*(.*)$", block, re.M)
        if task and expected:
            cases.append((block.split()[0].strip(), task.group(1),
                          "policy_refused" in expected.group(1)))
    return cases


DEV_CASES = _dev_cases()


def test_the_dev_split_actually_parsed():
    """A corpus that silently matched nothing passes every test built on it. This is the
    same vacuity the postcondition check fails closed on (A11.7), one level up.

    The expected count comes from the split's own title, so growing the set is one edit
    rather than a number here that drifts out of date without saying so.
    """
    title = (REPO / "eval" / "dev-set.md").read_text(encoding="utf-8").splitlines()[0]
    declared = int(re.search(r"\((\d+) cases\)", title).group(1))
    assert len(DEV_CASES) == declared, f"parsed {len(DEV_CASES)} of {declared} cases"
    assert any(refused for _, _, refused in DEV_CASES)
    assert any(not refused for _, _, refused in DEV_CASES)


@pytest.mark.parametrize("case_id,task,must_refuse",
                         DEV_CASES, ids=[c[0] for c in DEV_CASES])
def test_admission_agrees_with_the_dev_split(case_id, task, must_refuse, classify):
    tier, reason = classify(task)
    if must_refuse:
        assert tier is Tier.REFUSED, f"{case_id} was admitted: {task!r}"
    else:
        assert tier is not Tier.REFUSED, (
            f"{case_id} refused as {reason!r}: {task!r}. This sentence was written to "
            f"describe a case, not to test the classifier, which is the whole reason it "
            f"can disagree with it.")


@pytest.mark.parametrize("task", DEMO_ACCEPTED)
def test_the_home_page_does_not_offer_a_task_it_will_refuse(task, classify):
    tier, reason = classify(task)
    assert tier is not Tier.REFUSED, f"chip refused as {reason!r}: {task!r}"


@pytest.mark.parametrize("task", DEMO_REFUSED)
def test_the_refusal_demonstration_still_refuses(task, classify):
    """The one chip that exists to show a refusal. If admission ever stops refusing it the
    home page silently loses its only visible example of the policy working."""
    tier, reason = classify(task)
    assert tier is Tier.REFUSED and reason, f"chip was admitted: {task!r}"


#: Ours, unavoidably — nothing outside this repo lists the acts we decline. Held to the
#: coverage rule below instead.
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


# --- tier: what the frontend reports about itself ----------------------------------

def test_a_task_that_maps_to_a_promised_record_is_declared(classify):
    """T-DECLARED is defined as mapping to a promised record (S-1.3), and nothing assigned
    it: every OP-4…OP-7 run was labelled best-effort, which understates the system in the
    one place the spec says must be visible, and empties the headline success rate."""
    from app.executor import PROMISED_RECORDS

    seen = set()
    for case_id, task, must_refuse in DEV_CASES:
        if must_refuse:
            continue
        tier, why = classify(task)
        if tier is Tier.DECLARED:
            seen.add(why)
    assert seen == {r.id for r in PROMISED_RECORDS}, (
        f"promised records no dev case reaches: {{r.id for r in PROMISED_RECORDS}} - {seen}")


def test_the_support_page_cannot_promise_an_operation_the_router_cannot_reach():
    """The page rendered "not yet implemented" for a milestone after these four shipped,
    because it was prose. It is data now, and this is what keeps the data honest."""
    from app.executor import PROMISED_RECORDS

    routes = dict(Executor.ROUTES)
    assert all(r.route in routes for r in PROMISED_RECORDS), (
        f"unreachable: {[r.id for r in PROMISED_RECORDS if r.route not in routes]}")


def test_an_undeclared_site_is_not_reported_as_declared(classify):
    """The other half. S-1.5 forbids giving experimental results declared weight, so the
    label has to be able to say no."""
    for task in ("On www.gutenberg.org, find the Science Fiction bookshelf",
                 "Read the reference code on some other website"):
        tier, _ = classify(task)
        assert tier is Tier.EXPERIMENTAL, task


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


# --- anchor ambiguity: the refusal to guess between two answers --------------------
#
# Ambiguity was tested; nothing asserted that a label appearing legitimately in more than
# one place still resolves when those places agree. A stricter rule would fail correct runs
# and read as `verification_mismatch` — a fail-closed control that is on and wrong.

AMBIGUOUS_TABLE = """
<html><body><table id="t">
  <tr><th>UPC</th><td>aaa111</td></tr>
  <tr><th>UPC</th><td>bbb222</td></tr>
</table></body></html>
"""

AGREEING_TABLE = """
<html><body>
  <table id="t"><tr><th>UPC</th><td>aaa111</td></tr></table>
  <table id="u"><tr><th>UPC</th><td>aaa111</td></tr></table>
</body></html>
"""

DISAGREEING_COLUMNS = """
<html><body>
  <table><tr><th>Symbol</th></tr><tr><td>AAPL</td></tr></table>
  <table><tr><th>Symbol</th></tr><tr><td>MSFT</td></tr></table>
</body></html>
"""

AGREEING_COLUMNS = """
<html><body>
  <table><tr><th>Symbol</th></tr><tr><td>AAPL</td></tr></table>
  <table><tr><th>Symbol</th></tr><tr><td>AAPL</td></tr></table>
</body></html>
"""

DISAGREEING_SORT_STATE = """
<html><body>
  <table><tr><th aria-sort="ascending">GICS Sector</th></tr><tr><td>x</td></tr></table>
  <table><tr><th aria-sort="descending">GICS Sector</th></tr><tr><td>y</td></tr></table>
</body></html>
"""

AGREEING_SORT_STATE = """
<html><body>
  <table><tr><th aria-sort="descending">GICS Sector</th></tr><tr><td>x</td></tr></table>
  <table><tr><th aria-sort="descending">GICS Sector</th></tr><tr><td>y</td></tr></table>
</body></html>
"""


def _spec(label: str, relation: Relation) -> ClaimSpec:
    return ClaimSpec(name="v", label=label, relation=relation, value_type="string")


DISAGREEING_DEFINITIONS = """
<html><body>
  <dl><dt>Stock</dt><dd>22 available</dd></dl>
  <dl><dt>Stock</dt><dd>none left</dd></dl>
</body></html>
"""

AGREEING_DEFINITIONS = """
<html><body>
  <dl><dt>Stock</dt><dd>22 available</dd></dl>
  <dl><dt>Stock</dt><dd>22 available</dd></dl>
</body></html>
"""

#: (extractor, html that must raise, html that must resolve, label, relation)
AMBIGUITY_CASES = (
    ("_table_row_cell", AMBIGUOUS_TABLE, AGREEING_TABLE, "UPC", Relation.TABLE_ROW_CELL),
    ("_table_column_cell", DISAGREEING_COLUMNS, AGREEING_COLUMNS, "Symbol",
     Relation.TABLE_COLUMN_CELL),
    ("_sort_state", DISAGREEING_SORT_STATE, AGREEING_SORT_STATE, "GICS Sector",
     Relation.SORT_STATE),
    ("_located_label", DISAGREEING_DEFINITIONS, AGREEING_DEFINITIONS, "Stock",
     Relation.LOCATED_LABEL),
)


def _call(name: str, html_text: str, label: str, relation: Relation):
    """`_located_label` takes the anchor the run located; the rest take it from the spec.
    The label is the same either way, which is the point of including it here."""
    from app import verifier

    tree = lxml_html.fromstring(html_text)
    spec = _spec("" if relation is Relation.LOCATED_LABEL else label, relation)
    if relation is Relation.LOCATED_LABEL:
        return verifier._located_label(tree, spec, {"v_anchor": label})
    return getattr(verifier, name)(tree, spec)


def test_every_place_that_can_refuse_as_ambiguous_has_a_case():
    """The same rule as the refusal-reason coverage above, applied to the verifier: a
    fourth `AnchorAmbiguous` raise added without a case would be a refusal nothing can
    tell apart from correct caution."""
    tree = ast.parse((REPO / "app" / "verifier.py").read_text(encoding="utf-8"))
    raising = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Raise) and isinstance(inner.exc, ast.Call)
                    and getattr(inner.exc.func, "id", "") == "AnchorAmbiguous"):
                raising.add(node.name)
    assert raising == {name for name, *_ in AMBIGUITY_CASES}, (
        f"no ambiguity case for: {raising - {name for name, *_ in AMBIGUITY_CASES}}")


@pytest.mark.parametrize("name,bad,_good,label,relation", AMBIGUITY_CASES,
                         ids=[c[0] for c in AMBIGUITY_CASES])
def test_disagreeing_anchors_refuse_rather_than_pick_one(name, bad, _good, label, relation):
    from app import verifier

    with pytest.raises(verifier.AnchorAmbiguous):
        _call(name, bad, label, relation)


@pytest.mark.parametrize("name,_bad,good,label,relation", AMBIGUITY_CASES,
                         ids=[c[0] for c in AMBIGUITY_CASES])
def test_an_anchor_that_repeats_but_agrees_still_resolves(name, _bad, good, label, relation):
    """The missing half. A label may legitimately appear more than once; what makes it
    unanswerable is the places disagreeing, not their number."""
    value, span, _path = _call(name, good, label, relation)
    assert value is not None and span


# --- the frozen postcondition hash (S-4.12) ---------------------------------------
#
# Tamper was tested; the pass case was only covered incidentally, by real runs happening to
# pass. That is weaker than it sounds — incidental coverage stops the moment runs stop.

FROZEN = Postcondition(
    goal="read the UPC",
    operation="book_detail",
    target_url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
    inputs={"label": "UPC"},
    required_actions=(RequiredAction("click", "A Light in the Attic", "reach the page"),),
    claims=(ClaimSpec(name="upc", label="UPC", relation=Relation.TABLE_ROW_CELL,
                      value_type="string"),),
    absence=AbsenceMode.B_ENUMERATION,
    coverage_anchor="//p[@class='counter']",
)


def test_the_frozen_postcondition_still_matches_itself():
    """The deliberate pass case. A hash check that only ever gets asked about tampered
    objects cannot be told apart from one that rejects everything, and this one sits in
    front of every verification in the system."""
    assert matches_frozen(FROZEN.to_dict(), FROZEN.sha256)


def test_key_order_does_not_change_the_digest():
    """How a hash check becomes always-on: a serialisation that depends on insertion order
    fails every honest run, and the failure reads as tampering."""
    shuffled = dict(reversed(list(FROZEN.to_dict().items())))
    assert matches_frozen(shuffled, FROZEN.sha256)


@pytest.mark.parametrize("key", sorted(FROZEN.to_dict()))
def test_every_frozen_field_is_load_bearing(key):
    """The coverage rule again: a field serialised but not actually covered by the hash is
    a field the run never committed to, and nothing else would ever say so."""
    data = FROZEN.to_dict()
    assert data[key], f"{key} is empty in the fixture, so this assertion proves nothing"
    value = data[key]
    if isinstance(value, str):
        data[key] = value + " (changed)"
    elif isinstance(value, dict):
        data[key] = {**value, "changed": True}
    else:
        data[key] = value[:-1] if len(value) > 1 else []
    assert digest(data) != FROZEN.sha256, f"changing {key} does not change the hash"
    assert not matches_frozen(data, FROZEN.sha256)


# --- the pinned model id ----------------------------------------------------------

MOVING_ALIASES = {
    "latest": "gemini-flash-latest",
    "preview": "gemini-3.0-pro-preview",
    "exp": "gemini-exp-1206",
    "experimental": "gemini-2.5-experimental",
}


def test_every_forbidden_marker_is_exercised():
    from app.provider import FORBIDDEN_MARKERS

    assert set(FORBIDDEN_MARKERS) == set(MOVING_ALIASES), (
        f"unexercised: {set(FORBIDDEN_MARKERS) - set(MOVING_ALIASES)}")


@pytest.mark.parametrize("marker,model_id", sorted(MOVING_ALIASES.items()))
def test_a_moving_alias_is_recognised(marker, model_id):
    from app.provider import looks_like_moving_alias

    assert looks_like_moving_alias(model_id), marker


def test_the_id_we_actually_ship_is_accepted():
    """The half that was only ever proven by the service starting. `exp` is a substring of
    plenty of ordinary words, and this rule refuses to boot — so the day it matches the
    pinned id, the system is down and the reason looks like policy."""
    from app.config import settings
    from app.provider import looks_like_moving_alias

    assert not looks_like_moving_alias(settings.provider.model_id), (
        f"the pinned model id {settings.provider.model_id!r} trips the moving-alias rule")

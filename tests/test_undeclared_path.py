"""The experimental tier has to browse, not just label (A13.2).

Before this, a task the keyword router did not recognise ended as
`unsupported / policy_refused` before a browser was opened. That reads as a decision about
the task and it was a fact about us: we had no script. The tier was answering "across
different sites" with a site count of two, and an abstention that never observed anything
cannot say the step it stopped at or the state it saw, which A2.2 requires.

What is asserted here is the shape of the weaker promise, because weaker is where it is
tempting to promise nothing: the site is frozen before browsing, the binding rule is frozen
before browsing, and code — not the model — re-reads the value from the label the run
located.
"""

from __future__ import annotations

import pytest
from lxml import html as lxml_html

from app.executor import Executor
from app.models import FailureClass, StepKind, TerminalStatus, Tier, TraceEntry
from app.postcondition import Relation
from app.verifier import AnchorAmbiguous, AnchorNotFound, _located_label, _same_site


@pytest.fixture()
def executor() -> Executor:
    return Executor.__new__(Executor)


# --- where to start ---------------------------------------------------------------

@pytest.mark.parametrize("task,expected", [
    ("Open https://example.org/catalogue/page-2.html and read the total",
     "https://example.org/catalogue/page-2.html"),
    ("On www.gutenberg.org, find the Science Fiction bookshelf and count the ebooks",
     "https://www.gutenberg.org/"),
    ("How many bugs are open on bugs.python.org/issues?", "https://bugs.python.org/issues"),
    ("What is the weather like tomorrow?", ""),
    ("Tell me the capital of France", ""),
])
def test_the_entry_point_comes_from_the_task_or_nowhere(task, expected):
    """Falling back to a search engine would mean starting somewhere the task never named,
    which is how a run ends up answering a question nobody asked."""
    assert Executor.resolve_entry(task) == expected


def test_a_task_with_no_entry_point_produces_a_reason_not_a_shrug():
    """A13.2.1: not being able to resolve one is itself the abstention reason."""
    assert Executor.__new__(Executor)._plan_generic("What is the capital of France?") is None


def test_the_goal_terms_are_the_words_the_task_is_about():
    terms = [t.lower() for t in
             Executor.goal_terms("On www.gutenberg.org, find the Science Fiction "
                                 "bookshelf and tell me how many ebooks it lists")]
    assert "science" in terms and "fiction" in terms and "ebooks" in terms
    assert "tell" not in terms and "the" not in terms and "www" not in terms


# --- what is frozen before browsing ------------------------------------------------

def test_the_undeclared_postcondition_is_weaker_but_not_absent(executor):
    plan = executor._plan_generic("On www.gutenberg.org, read the Science Fiction shelf")
    pc = plan.postcondition

    assert pc.target_url == "https://www.gutenberg.org/"
    assert pc.inputs["url_scope"] == "site"
    assert [c.name for c in pc.claims] == ["answer"]
    assert pc.claims[0].relation is Relation.LOCATED_LABEL
    # The label cannot be known in advance on a site nobody declared. That it is empty is
    # the documented weakening, and it is why the *rule* has to be frozen instead.
    assert pc.claims[0].label == ""
    assert pc.sha256


def test_an_undeclared_run_is_never_scripted(executor):
    """There is no script for a site nobody declared; that is what makes it generic."""
    executor._provider = type("P", (), {"configured": staticmethod(lambda: False)})()
    plan = executor._plan_generic("Read https://example.org/x")
    planned, why = executor._choose_path(plan, False, True)
    assert planned and "generic" in why


def test_the_frozen_site_still_rejects_evidence_from_somewhere_else():
    assert _same_site("https://www.gutenberg.org/ebooks/1", "https://gutenberg.org/")
    assert not _same_site("https://en.wikipedia.org/wiki/X", "https://gutenberg.org/")
    assert not _same_site("http://gutenberg.org/", "https://gutenberg.org/")
    assert not _same_site(None, "https://gutenberg.org/")


# --- the candidate is produced by code, not reported by the model ------------------

#: What an `extract` records: the label the model named, and the markup of the element it
#: pointed at. The model points; code reads.
INFOBOX = ("<table><tr><th>UPC</th><td>a897fe39b1053632</td></tr>"
           "<tr><th>Availability</th><td>In stock (22 available)</td></tr></table>")


def _extract_step(seq: int, anchor: str, fragment: str, ok: bool = True) -> TraceEntry:
    return TraceEntry(seq=seq, kind=StepKind.EXTRACT, summary="extract", ok=ok,
                      detail={"args": {"ref": "e1", "label_anchor": anchor},
                              "observed": "whatever the element rendered as",
                              "fragment": fragment})


class _Ctx:
    def __init__(self, run):
        self.run = run
        self.candidate: dict = {}


def test_the_candidate_is_read_from_the_label_not_from_what_was_pointed_at(executor):
    """The model points at the table, because the reduced view offers the table and not its
    cells. Taking that text verbatim would compare a whole infobox against one value and
    fail every time for a reason that has nothing to do with the answer."""
    from app.models import Run, new_id

    run = Run(id=new_id("run"), task="t", tier=Tier.EXPERIMENTAL)
    run.trace = [_extract_step(1, "Availability", INFOBOX)]
    ctx = _Ctx(run)

    import asyncio
    asyncio.run(executor._read_generic(ctx))
    assert ctx.candidate == {"answer": "In stock (22 available)",
                             "answer_anchor": "Availability"}


def test_an_extraction_with_no_label_yields_no_candidate(executor):
    """A value with nothing holding it to the page is a reading, not a verification, and
    the vacuity check (A11.7) is what turns that into an abstention."""
    from app.models import Run, new_id

    run = Run(id=new_id("run"), task="t", tier=Tier.EXPERIMENTAL)
    run.trace = [_extract_step(1, "", INFOBOX),
                 _extract_step(2, "Delivery estimate", INFOBOX)]
    ctx = _Ctx(run)

    import asyncio
    asyncio.run(executor._read_generic(ctx))
    assert ctx.candidate == {}


# --- the verifier re-reads it, from the label, in the stored artifact ---------------

PRODUCT = """
<html><body><table>
  <tr><th>UPC</th><td>a897fe39b1053632</td></tr>
  <tr><th>Availability</th><td>In stock (22 available)</td></tr>
</table></body></html>
"""


def _spec():
    from app.postcondition import ClaimSpec

    return ClaimSpec(name="answer", label="", relation=Relation.LOCATED_LABEL,
                     value_type="string")


def test_the_value_is_re_read_from_the_label_the_run_located():
    value, span, anchor = _located_label(lxml_html.fromstring(PRODUCT), _spec(),
                                         {"answer_anchor": "Availability"})
    assert value == "In stock (22 available)"
    assert "Availability" in anchor


def test_a_label_that_is_not_in_the_artifact_fails_the_claim():
    """The model can name any label it likes. Only one that resolves in the stored bytes
    verifies anything."""
    with pytest.raises(AnchorNotFound):
        _located_label(lxml_html.fromstring(PRODUCT), _spec(),
                       {"answer_anchor": "Delivery estimate"})


def test_a_label_with_nothing_bound_to_it_fails_the_claim():
    """It is on the page, so a proximity rule would happily return whatever is nearby. The
    binding is structural or it does not exist."""
    html_text = "<html><body><p>Availability</p></body></html>"
    with pytest.raises(AnchorNotFound):
        _located_label(lxml_html.fromstring(html_text), _spec(),
                       {"answer_anchor": "Availability"})


def test_a_run_that_reports_no_label_verifies_nothing():
    with pytest.raises(AnchorNotFound):
        _located_label(lxml_html.fromstring(PRODUCT), _spec(), {})


@pytest.mark.parametrize("html_text,label,expected", [
    ("<html><body><dl><dt>Stock</dt><dd>22</dd></dl></body></html>", "Stock", "22"),
    ("<html><body><label for='q'>Query</label><input id='q' value='lantern'>"
     "</body></html>", "Query", "lantern"),
    ("<html><body><span>Total</span><span>110 results</span></body></html>", "Total",
     "110 results"),
])
def test_the_binding_rules_are_the_structural_ones(html_text, label, expected):
    value, _span, _anchor = _located_label(lxml_html.fromstring(html_text), _spec(),
                                           {"answer_anchor": label})
    assert value == expected

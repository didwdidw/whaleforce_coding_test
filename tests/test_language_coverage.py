"""The declared promise has a language, and a check that could not run has a value (A19).

Two separate things live here because they were found together. The promise was English-only
and nothing said so — the graders' own assignment ships in Traditional Chinese — and the
constraint that binds a run to the site its task named wrote itself down as *satisfied* on
every task whose site it could not read. The second is worse: a safeguard that reports a
pass when it did not run is the vacuous verification A11.7 is about, sitting inside the
newest safeguard we built.
"""

from __future__ import annotations

import pytest

from app.executor import Executor
from app.models import FailureClass, Run, TerminalStatus, Tier, new_id
from app.postcondition import ClaimSpec, Postcondition, Relation
from app.records import named_site
from app.store import Store
from app.verifier import Check, Verifier

WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")


# ---- the promise, in Chinese (A19.4, A-59) ---------------------------------------

@pytest.mark.parametrize("task,host,record", [
    ("在維基百科的 List of S&P 500 companies 條目裡，依 GICS Sector 由大到小排序，告訴我第一列",
     "en.wikipedia.org", "OP-4"),
    ("在維基百科那篇 List of S&P 500 companies 條目裡展開摺疊的 navbox，告訴我 Energy 那一組",
     "en.wikipedia.org", "OP-5"),
    ("到 books.toscrape.com 的非小說分類，讀第二頁的結果", "books.toscrape.com", "OP-6"),
    ("到 books.toscrape.com 的 A Light in the Attic 商品詳情，讀它的產品資訊",
     "books.toscrape.com", "OP-7"),
])
def test_a_promised_record_asked_for_in_chinese_is_declared(task, host, record):
    """A tier is a promise, and a promise that weakens depending on the language it was
    asked in is a promise with an undeclared condition."""
    assert named_site(task) == host
    assert Executor.classify(Executor.__new__(Executor), task) == (Tier.DECLARED, record)


@pytest.mark.parametrize("task,refusal", [
    ("登入我的券商帳戶，告訴我餘額", "authentication or a login flow"),
    ("幫我把這本書加入購物車並結帳", "a transaction or a state change"),
    ("幫我在這個商品底下發表評論", "writing to a third party"),
    ("幫我解掉這個頁面的驗證碼", "an anti-bot challenge"),
])
def test_the_refusals_are_in_chinese_too(task, refusal):
    """A19.5. These went in before the capabilities did: a build that declines an English
    "log into my brokerage account" and attempts the same sentence in Chinese would be
    worse than one that declines both."""
    assert Executor.classify(Executor.__new__(Executor), task) == (Tier.REFUSED, refusal)


def test_the_chinese_alias_table_does_not_fire_on_english_word_boundaries():
    """The two writing systems need two matching rules, and neither may leak into the
    other: `\\b` never fires between 「維基百科」 and the 「的」 after it, and a bare
    substring rule in English would make `resort` match `sort`."""
    assert named_site("please unwikipedia this sentence") == ""
    assert named_site("在維基百科的條目裡") == "en.wikipedia.org"
    assert Executor._task_names("please resort the list", "sort") is False
    assert Executor._task_names("依 GICS Sector 由大到小排序", "由大到小") is True


# ---- a constraint that could not be evaluated (A19.2, A19.3, A-58) ---------------

def _postcondition(**kw) -> Postcondition:
    return Postcondition(
        goal="read the labelled field", operation="OP-7", target_url=WIKI,
        claims=(ClaimSpec("upc", "UPC", Relation.TABLE_ROW_CELL, "text"),), **kw)


def _run_with(store: Store, task: str, pc: Postcondition) -> tuple[Run, str]:
    run = Run(id=new_id("run"), task=task, tier=Tier.EXPERIMENTAL)
    run.postcondition = pc.to_dict()
    run.postcondition_hash = pc.sha256
    store.save_run(run)
    artifact = store.put_artifact(
        run.id, "dom:step-1", b"<table><tr><th>UPC</th><td>abc123</td></tr></table>",
        source_url=WIKI, media_type="text/html")
    return run, artifact.id


def test_an_unreadable_site_is_recorded_as_unevaluated_not_as_satisfied(store):
    """It appended `named_site_frozen: True`. Nothing had been compared."""
    run, artifact = _run_with(store, "read the labelled field on that page",
                              _postcondition())

    verdict = Verifier(store).verify(run, artifact_id=artifact,
                                     candidate={"upc": "abc123"})

    check = next(c for c in verdict.checks if c.name == "named_site_frozen")
    assert check.ok is None and check.evaluated is False
    assert check.to_dict()["evaluated"] is False
    named = [u for u in verdict.evidence_summary["unevaluated_checks"]
             if u["check"] == "named_site_frozen"]
    assert named, "an unevaluated constraint is named, not counted"


def test_a_model_proposed_entry_point_with_no_site_binding_fails_closed(store):
    """A19.3. A18.3 lets the model choose where to start and A17.1 is what stops that
    choice from being unconstrained. Unevaluated, nothing constrains it — the defect A17.1
    was written for, reached from the other side. There is no combination in which nothing
    constrains where a run started."""
    run, artifact = _run_with(store, "read the labelled field on that page",
                              _postcondition(entry_point_source="model"))

    verdict = Verifier(store).verify(run, artifact_id=artifact,
                                     candidate={"upc": "abc123"})

    assert verdict.status is TerminalStatus.FAILED
    assert verdict.failure_class is FailureClass.VERIFICATION_MISMATCH
    assert "proposed by the model" in verdict.explanation
    assert verdict.counts_as_success is False


def test_the_same_run_proceeds_when_the_task_itself_resolved_the_entry_point(store):
    """The guard is about who chose, not about the constraint being absent: a task-resolved
    entry point is still frozen in `target_url`, which is a constraint the run did not
    write for itself."""
    run, artifact = _run_with(store, "read the labelled field on that page",
                              _postcondition())

    verdict = Verifier(store).verify(run, artifact_id=artifact,
                                     candidate={"upc": "abc123"})

    assert verdict.status is not TerminalStatus.FAILED


def test_an_unevaluated_check_does_not_make_a_run_look_verified():
    """A19.2's second half, at the level the vacuity guard reads: a run whose only checks
    could not be evaluated has not verified anything."""
    from app.verifier import Verifier as V

    vacuous = V._vacuous(
        Postcondition(goal="g", operation="OP-7", target_url=WIKI,
                      claims=(ClaimSpec("upc", "UPC", Relation.TABLE_ROW_CELL, "text"),)),
        [], [Check("named_site_frozen", None, {})])
    assert vacuous, "every check unevaluated is not every check passing"

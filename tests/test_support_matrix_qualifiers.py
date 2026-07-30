"""A promised record may not advertise breadth its own limitations list denies.

`/support` is the one table in this submission whose selling point is that a reader can
overturn it. It carried OP-5 as an unqualified `implemented` while the build's most
important hole was in OP-5: the ordinal form of a row group is never answered. Searching
the whole page for `row group`, `ordinal` or `Hardware` returned nothing.

So the rule is that a qualifier and an executable entry come together — the row says how
far it reaches, and the entry it cites is a task somebody can run to check. And the
committed report has to have been produced by the list as it currently stands, which is
defect 19's shape: a check that covered seven entries, published under a table of eight.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app.limitations import LIMITATIONS, UNPINNED
from app.postcondition import ANSWERS_A_VALUE, Relation
from app.records import PROMISED_RECORDS

RESULTS = pathlib.Path(__file__).parent.parent / "eval" / "results"
ENTRY = {limit.id: limit for limit in LIMITATIONS}


@pytest.fixture()
def support_page(tmp_path) -> str:
    """The rendered page, on a store of this test's own.

    One handle is shared by every reader in the deployment, and a module that entered the
    app's lifespan earlier in the session has already closed it — so the page is fetched
    through a fresh store swapped into all of its holders, as `/healthz` reads several."""
    from app import server
    from app.store import Store

    fresh = Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")
    holders = [(server.state, "store"), (server.state.coverage, "_store"),
               (server.state.provider, "ledger"), (server.state.executor, "_store"),
               (server.state.executor._coverage, "_store"),
               (server.state.executor._verifier, "_store"),
               (server.state.executor._locator_memory, "_store")]
    previous = [(obj, name, getattr(obj, name)) for obj, name in holders]
    for obj, name in holders:
        setattr(obj, name, fresh)
    try:
        yield TestClient(server.app, raise_server_exceptions=False).get("/support").text
    finally:
        for obj, name, value in previous:
            setattr(obj, name, value)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("&#39;", "'").replace("&amp;", "&")
                  .replace("&#34;", '"').replace("&quot;", '"'))


def _plan(task: str):
    from app.executor import Executor

    ex = Executor.__new__(Executor)
    return ex._select_plan(task) or ex._undeclared_plan(task)


def test_every_qualifier_cites_an_entry_a_reader_can_run():
    """A qualifier that says "this is narrower than it looks" and stops there is prose. The
    entry it names is what makes it checkable, so the citation is required."""
    qualified = [r for r in PROMISED_RECORDS if r.qualified]
    assert qualified, "OP-5 is qualified in this build; a matrix with none is the defect"
    for record in qualified:
        cited = re.findall(r"L-\d+", record.qualified)
        assert cited, f"{record.id}: qualified with no entry to reproduce it"
        for entry_id in cited:
            assert entry_id in ENTRY, f"{record.id} cites {entry_id}, which is not published"


def test_the_qualifier_reaches_the_page(support_page):
    body = _flat(support_page)
    for record in PROMISED_RECORDS:
        if record.qualified:
            assert _flat(record.qualified) in body, (
                f"{record.id}'s qualifier is in the code and not on the page")


def test_the_page_answers_the_search_that_found_nothing(support_page):
    body = _flat(support_page).lower()
    for term in ("row group", "ordinal", "hardware"):
        assert term in body, f"a reader searching {term!r} still finds nothing"


def test_the_ordinal_form_and_its_remedy_differ_in_what_can_be_bound():
    """The entry's claim about *why* — the label itself was asked for, so no anchor can be
    frozen for it — is checkable without a network: the ordinal phrasing compiles a claim
    with no label, the named phrasing compiles one with a label to re-read."""
    limit = ENTRY["L-8"]
    asked = _plan(limit.task)
    named = _plan(limit.remedy_task)

    unbindable = [c for c in asked.postcondition.claims
                  if c.relation is Relation.LOCATED_LABEL and not c.label]
    assert unbindable, "the ordinal form must leave the asked-for value unbound"
    answering = [c for c in named.postcondition.claims
                 if c.relation in ANSWERS_A_VALUE and not c.optional]
    assert answering and all(c.label for c in answering), (
        "the remedy must freeze a label, or it is not a remedy for this limitation")


def test_the_committed_check_covers_the_list_as_it_stands_now():
    """A-73 with the count checked. The report is what the support page points a reader at;
    if it was produced by a shorter list, it reports coverage it does not have."""
    published = {limit.id for limit in LIMITATIONS}
    covered = []
    for report in sorted(RESULTS.glob("limitations-*.json")):
        data = json.loads(report.read_text("utf-8"))
        if {r["id"] for r in data.get("results", [])} == published:
            covered.append((data.get("checked_at", ""), report.name, data))
    assert covered, (
        f"no committed report ran exactly these {len(published)} entries — re-run "
        f"`python -m eval.limitations_check --base-url <deployment>` and commit the report")
    _, name, data = max(covered)
    assert not data["do_not_reproduce"], (
        f"{name}: entries that do not reproduce as written: {data['do_not_reproduce']}")


def test_a_pinned_class_was_measured_on_the_sentence_that_publishes_it():
    """One phrasing family, two loud failures: DEV-04's ordinal form ends
    `unsupported / postcondition_unmet` and DEV-05's count form ends
    `failed / budget_exhausted`. An entry may pin a class only for its own sentence, and the
    newest report is the measurement — so pinning is checked against it rather than against
    the reasoning that chose it."""
    published = {limit.id for limit in LIMITATIONS}
    reports = []
    for report in sorted(RESULTS.glob("limitations-*.json")):
        data = json.loads(report.read_text("utf-8"))
        if {r["id"] for r in data.get("results", [])} == published:
            reports.append((data.get("checked_at", ""), data))
    _, data = max(reports)
    for result in data["results"]:
        limit = ENTRY[result["id"]]
        if limit.failure_class == UNPINNED:
            continue
        assert result["observed"]["failure_class"] == limit.failure_class, (
            f"{limit.id} pins {limit.failure_class!r} and the check observed "
            f"{result['observed']['failure_class']!r} — pin what was measured, or say "
            f"UNPINNED out loud")

"""A promised record holds for the values of its parameters, not for one (A25.2, A-74).

A18.1 held that a record is `site × operation` and the page is a parameter of it. OP-7's plan
had the parameter frozen — one title, one category URL, one selector — so asking for a
labelled field on any *other* books.toscrape product, which is precisely OP-7's declared
operation, fell to T-EXPERIMENTAL with the best-effort banner. That made the published
support matrix false in the same way L-1 was, and worse: it meant the headline declared rate
described a surface almost nobody would land on.

These tests use titles and articles that appear in no eval case, which is the only way to
tell a record from a fixture.
"""

from __future__ import annotations

import pytest

from app.executor import Executor
from app.models import Tier


def _classify(task: str) -> tuple[Tier, str | None]:
    return Executor.classify(Executor.__new__(Executor), task)


def _plan(task: str):
    return Executor._select_plan(Executor.__new__(Executor), task)


# ---- OP-7: the product is the parameter -------------------------------------------

@pytest.mark.parametrize("task,title", [
    ("On books.toscrape.com, open the product page for Sharp Objects and tell me its UPC.",
     "Sharp Objects"),
    ("On books.toscrape.com, open 'Tipping the Velvet' and read its labelled product "
     "information.", "Tipping the Velvet"),
    ("On books.toscrape.com, tell me the UPC of Set Me Free.", "Set Me Free"),
    ("到 books.toscrape.com 的 Sharp Objects 商品詳情，讀它的產品資訊", "Sharp Objects"),
])
def test_op7_holds_for_a_product_no_eval_case_names(task, title):
    assert _classify(task) == (Tier.DECLARED, "OP-7")
    plan = _plan(task)
    assert plan.postcondition.inputs["title"] == title
    # The frozen goal is about the product asked for, not about the one we happened to build
    # the plan around first.
    assert title in plan.postcondition.goal


def test_a_task_naming_no_product_gets_no_plan_rather_than_a_default():
    """Falling back to a canned product would answer about a book the task never named and
    verify it perfectly — the defect this generalisation removes, reintroduced as a default
    value. No plan means the run goes to the generic path, which is the honest outcome."""
    assert _plan("On books.toscrape.com, tell me the UPC.") is None


def test_the_original_declared_instance_still_works():
    task = ("Open the product detail page for A Light in the Attic and read its labelled "
            "product information")
    assert _classify(task) == (Tier.DECLARED, "OP-7")
    plan = _plan(task)
    assert plan.postcondition.inputs["title"] == "A Light in the Attic"
    # It keeps its direct entry point; the site's detail URLs carry an opaque id, so for any
    # other product the run has to reach it from the listing rather than guess a URL.
    assert plan.postcondition.target_url.endswith("a-light-in-the-attic_1000/index.html")


# ---- the other three records were checked for the same freeze ---------------------

def test_op4_takes_its_article_column_and_direction_from_the_task():
    task = ("On the Wikipedia List of largest companies by revenue article, sort the table "
            "by Revenue descending and tell me the top row.")
    assert _classify(task) == (Tier.DECLARED, "OP-4")
    pc = _plan(task).postcondition
    assert pc.inputs == {"sort_column": "Revenue", "direction": "descending"}
    assert pc.target_url.endswith("/wiki/List_of_largest_companies_by_revenue")


def test_op5_takes_its_article_from_the_task():
    task = ("On the Wikipedia article for Tesla, Inc., expand the first collapsed box at "
            "the foot of the page and tell me its title.")
    assert _classify(task) == (Tier.DECLARED, "OP-5")
    assert "Tesla" in _plan(task).postcondition.target_url


def test_op6_takes_its_category_and_page_from_the_task():
    task = "Go to the Travel category listing on books.toscrape.com and read the first page."
    assert _classify(task) == (Tier.DECLARED, "OP-6")
    assert _plan(task).postcondition.inputs["category"] == "Travel"


def test_the_trailing_noun_is_stripped_from_an_article_title():
    """A25.1's mechanical cause. Leading stopwords were stripped and the trailing noun was
    not, so the phrasing our own limitations list published as the fix resolved to
    `/wiki/List_of_S%26P_500_companies_article`."""
    for phrasing in ("the List of S&P 500 companies article on Wikipedia",
                     "the List of S&P 500 companies Wikipedia page",
                     "the Wikipedia list of S&P 500 companies"):
        assert Executor.wikipedia_article(f"In {phrasing}, sort by CIK ascending.").endswith(
            "/wiki/List_of_S%26P_500_companies"), phrasing

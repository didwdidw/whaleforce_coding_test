"""The one independent oracle: OP-4's expected top row (A25.4, A-76).

Of the five broken-instrument defects in this project, four scored correct work as wrong and
one — declared oracles that were never implemented — made unproven work look proven. This is
the fix for the fifth, and the reason it is worth an hour rather than a disclosure is the
trap the case was written around: **the same column sorted numerically and lexicographically
gives different top rows, and both orderings look completely reasonable on the page.**

The tests run offline against markup passed in directly, because what has to be right is the
sort-key decision, not the fetch.
"""

from __future__ import annotations

from eval.harness import independent_oracle
from eval.oracles import agrees_with, expected_top_row, sort_key_kind

URL = "https://en.wikipedia.org/wiki/Example"


def _table(rows: list[tuple[str, str]], header: str = "CIK") -> str:
    body = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows)
    return (f"<html><body><table class='wikitable sortable'>"
            f"<tr><th>Security</th><th>{header}</th></tr>{body}</table></body></html>")


def test_a_zero_padded_id_column_sorts_numerically():
    """The trap. As text `0000001800` sorts before `0000000320`; as numbers it does not, and
    the top row is a different company."""
    html = _table([("Apple", "0000320193"), ("Abbott", "0000001800"),
                   ("Amcor", "0001748790")])

    out = expected_top_row(URL, "CIK", "ascending", html=html)

    assert out["sort_key"] == "numeric"
    assert out["expected_top_row"] == ["Abbott", "0000001800"]


def test_a_column_with_any_non_numeric_cell_sorts_as_text():
    """`numeric` only when every non-blank cell reads as one — otherwise a mostly-numeric
    column would be sorted numerically on a guess, which is the same class of decision the
    product refuses to make."""
    html = _table([("Apple", "0000320193"), ("Abbott", "n/a"), ("Amcor", "see note")])

    out = expected_top_row(URL, "CIK", "ascending", html=html)

    assert out["sort_key"] == "lexicographic"


def test_a_blank_cell_does_not_make_a_numeric_column_textual():
    assert sort_key_kind(["12", "—", "3"]) == "numeric"
    assert sort_key_kind(["12", "1990–1995", "3"]) == "lexicographic"
    assert sort_key_kind(["12", "3 of 40"]) == "lexicographic"


def test_descending_takes_the_other_end():
    html = _table([("Apple", "0000320193"), ("Abbott", "0000001800")])
    out = expected_top_row(URL, "CIK", "descending", html=html)
    assert out["expected_top_row"] == ["Apple", "0000320193"]


def test_a_column_the_page_does_not_have_is_unavailable_not_wrong():
    out = expected_top_row(URL, "Revenue", "ascending", html=_table([("Apple", "1")]))
    assert out["available"] is False and "Revenue" in out["why"]
    # And an unavailable oracle is not comparable, so it can never become a finding.
    assert agrees_with(out, {"Security": "Apple"})["comparable"] is False


def test_the_derivation_is_reported_not_just_the_answer():
    """A ground truth nobody can audit is another assertion."""
    out = expected_top_row(URL, "CIK", "ascending", html=_table([("Apple", "3"), ("A", "1")]))
    assert out["headers"] == ["Security", "CIK"]
    assert out["column_index"] == 1
    assert out["rows_considered"] == 2
    assert out["sort_key"] == "numeric"


# ---- how scoring uses it ----------------------------------------------------------

def _run(value, column="CIK", direction="ascending"):
    return {"postcondition": {"target_url": URL,
                              "inputs": {"sort_column": column, "direction": direction}},
            "claims": [{"name": "top_row", "ok": True,
                        "evidence": {"normalised_value": value}}]}


def test_only_op4_gets_a_derivation_and_the_rest_say_so(monkeypatch):
    """The honesty half of A25.4: a case with no independent oracle says it has none rather
    than reporting a check it did not do."""
    out = independent_oracle({"record": "OP-6"}, _run({"Security": "Apple"}))
    assert out["kind"] == "evidence re-check only"
    assert "no independent derivation" in out["why"]


def test_a_disagreement_is_reported_with_what_was_expected(monkeypatch):
    import eval.harness as harness

    monkeypatch.setattr(
        harness, "independent_oracle", harness.independent_oracle)  # keep the real one
    monkeypatch.setattr("eval.oracles.fetch",
                        lambda url, timeout=20.0: _table([("Abbott", "0000001800"),
                                                          ("Apple", "0000320193")]))

    agreed = independent_oracle({"record": "OP-4"}, _run({"Security": "Abbott"}))
    assert agreed["agrees"] is True

    wrong = independent_oracle({"record": "OP-4"}, _run({"Security": "Apple"}))
    assert wrong["agrees"] is False
    assert wrong["not_in_expected_row"] == ["apple"]
    assert wrong["expected_top_row"] == ["Abbott", "0000001800"]


def test_a_run_that_reported_no_row_is_not_scored_against_the_oracle(monkeypatch):
    monkeypatch.setattr("eval.oracles.fetch", lambda url, timeout=20.0: _table([("A", "1")]))
    run = _run({"Security": "A"})
    run["claims"] = []
    assert independent_oracle({"record": "OP-4"}, run)["comparable"] is False

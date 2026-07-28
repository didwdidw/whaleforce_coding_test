"""Known limitations, as tasks a reader can run rather than as prose (A14.8).

S-11.4 required the list to exist and nothing defined what an entry was, so it drifted into
the shape every limitations list drifts into: general statements about the class of thing
that might go wrong, none of which anybody can check.

Each entry here names a task **as a person would type it**, what the system actually does
with it, why, and the `terminal_status` / `failure_class` it ends with. Every one was run
against a live deployment and the outcome recorded is the one observed. That makes them
reproducible, and it makes them falsifiable: if a build fixes one, the entry is wrong and
somebody will find out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Limitation:
    id: str
    task: str
    outcome: str
    failure_class: str | None
    what_happens: str
    why: str
    #: A phrasing the entry claims makes the same task work. It is part of what the entry
    #: says, so it is part of what has to reproduce (A25.1): L-1 published a remedy that
    #: resolved to `/wiki/List_of_S%26P_500_companies_article` and ended `unsupported`.
    #: `eval.limitations_check` runs both against the deployment.
    remedy_task: str = ""
    remedy_outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "task": self.task, "outcome": self.outcome,
                "failure_class": self.failure_class,
                "what_happens": self.what_happens, "why": self.why,
                "remedy_task": self.remedy_task, "remedy_outcome": self.remedy_outcome}


LIMITATIONS: tuple[Limitation, ...] = (
    Limitation(
        id="L-1",
        task=("In the S&P 500 constituents table on Wikipedia, sort by CIK ascending "
              "and tell me which company is first."),
        outcome="unsupported",
        failure_class="policy_refused",
        what_happens=("The run stops before browsing and says it has nowhere to begin, "
                      "asking for a URL or an article title."),
        why=("The article is described rather than named. 'The S&P 500 constituents "
             "table on Wikipedia' does not resolve to one page title, and the alternative "
             "— searching for it and picking a result — is choosing a starting page the "
             "task never named. Naming the article makes the same task succeed; the exact "
             "phrasing that does is below, and it is run against the deployment with the "
             "entry itself."),
        remedy_task=("In the List of S&P 500 companies article on Wikipedia, sort by CIK "
                     "ascending and tell me which company is first."),
        remedy_outcome="succeeded_verified",
    ),
    Limitation(
        id="L-2",
        task="How many books are listed on the last page of the Nonfiction category on books.toscrape.com?",
        outcome="failed",
        failure_class="budget_exhausted",
        what_happens=("The run reaches the 25-step budget while paging and stops without "
                      "an answer."),
        why=("'The last page' is reached by paging until the next control disappears. Each "
             "page costs a model call and a step on the model-driven path, and Nonfiction "
             "is long enough to exceed the budget before the end. The budget is "
             "fail-closed by design: the alternative is reporting the page it happened to "
             "reach as though it were the last one, which is the failure this system is "
             "built to refuse."),
    ),
    Limitation(
        id="L-3",
        task="Is there any book in the Fiction category on books.toscrape.com priced over £50?",
        outcome="unverified",
        failure_class="postcondition_unmet",
        what_happens=("The run enumerates the first page, compares 20 items against the "
                      "listing's own count of 65, and reports that coverage is unproven."),
        why=("Absence is only ever concluded from a positive proof (A3.2), and the proof "
             "is that every member of the result set was re-read from a stored artifact. "
             "A category spanning several pages spans several artifacts, and this build "
             "verifies a claim against one. A single-page category — Poetry, Travel — is "
             "proven and answered. The multi-page case is reported as unverified rather "
             "than answered from the page we happened to see."),
    ),
    Limitation(
        id="L-4",
        task="Use Wikipedia's search page to find articles mentioning 'convertible arbitrage'.",
        outcome="blocked",
        failure_class="policy_refused",
        what_happens=("The run refuses before navigating and quotes the robots rule that "
                      "caused it."),
        why=("Wikipedia's robots.txt disallows `/wiki/Special:Search`. The refusal is "
             "correct and it is also a limitation: any task whose only route runs through "
             "a disallowed path has no answer here, however ordinary the question is."),
    ),
    Limitation(
        id="L-5",
        task="On www.gutenberg.org, find the 'Science Fiction' bookshelf and tell me how many ebooks it lists.",
        outcome="unsupported",
        failure_class="postcondition_unmet",
        what_happens=("The run browses the site, then abstains naming the step it stopped "
                      "at, the page it was on and which part of the postcondition it could "
                      "not satisfy."),
        why=("An experimental-tier run freezes the site and the binding rule but cannot "
             "freeze the label — nobody knows it in advance on a site never seen. When the "
             "model cannot point at a value bound to a label it can name, there is nothing "
             "for code to re-read, and the run abstains. Sometimes it succeeds instead; "
             "which of the two happens is a property of the page, and the experimental "
             "split is where that rate is measured rather than asserted."),
    ),
    Limitation(
        id="L-6",
        task="Go to the nonfiction category listing on books.toscrape.com and read the second page of results, without the planner.",
        outcome="succeeded_verified",
        failure_class=None,
        what_happens=("The run answers correctly, but on the deterministic path rather "
                      "than the model-driven one."),
        why=("The two paths satisfy the same postcondition and are verified the same way, "
             "and the deterministic one is what the pinned demonstrations use so the "
             "frontend stays inspectable with no provider quota. It is not evidence of "
             "self-correction: no model is in that loop. Every run records which path it "
             "took, and the reported rates are given per path, because a figure mixing "
             "them describes neither."),
    ),
    Limitation(
        id="L-7",
        task="Search the fixture catalogue for a term that appears on no page",
        outcome="unsupported",
        failure_class="postcondition_unmet",
        what_happens=("An abstention that may be caused by our own page reduction rather "
                      "than by the site — in which case the run carries a badge saying it "
                      "is not a clean abstention."),
        why=("The reduced view sent to the model has an element cap. When the goal names "
             "elements that the cap dropped, an honest 'I could not see it' is produced by "
             "a page that had it. Runs are audited for that condition and marked, but the "
             "audit only covers what we thought to look for: an abstention caused by "
             "something we have no counter for is indistinguishable from a correct one."),
    ),
)


def limitations() -> list[dict[str, Any]]:
    return [limit.to_dict() for limit in LIMITATIONS]

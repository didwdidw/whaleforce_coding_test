# Fail-closed controls: which ones can tell "on and right" from "on and wrong"

**Date:** 2026-07-27. Companion to `docs/m8-quiet-failures.md`, which is the general form of
this problem.

We already had one half of it: *a control whose failure mode is closed ends up closed*,
because nothing complains when it refuses. This is the mirror, and it is the more expensive
one. **A control that is always on and judging wrongly is indistinguishable from one that is
on and judging correctly.** Both produce refusals. Refusals look like caution. Nobody files a
bug against caution.

Two were found this way in one afternoon, both live:

- `_same_page` compared URL paths without decoding percent-escapes, so
  `List_of_S%26P_500_companies` and `List_of_S&P_500_companies` were two different pages and
  correct runs were rejected as answering the wrong question.
- The out-of-scope classifier matched nouns rather than acts. A bare `order` refused *"sort
  in descending order"*; `book a` refused *"read the product page for the book A Light in the
  Attic"* — our own OP-7 dev case in natural phrasing. Live since M1.

Neither produced a single complaint, because both failure modes are a refusal.

## What makes one checkable

A corpus with **both halves**: what it must refuse, and what it must not. A test suite that
only asserts refusals passes just as happily when the control refuses everything — which is
the state the out-of-scope classifier was actually in.

`tests/test_fail_closed_controls.py` is that corpus for the two above. The inventory below is
every other fail-closed judgement in the system, marked by whether anything today could tell
the two states apart.

## The inventory

| Control | Where | Refusal it produces | Can we tell "right" from "always-on"? |
|---|---|---|---|
| robots matching (RFC 9309) | `app/robots.py` | `blocked / robots_disallowed` | **Yes.** `test_robots_semantics.py` asserts both directions on two real robots.txt files, including that the OP-4 article is *allowed* by the same file that Disallows `Special:` |
| robots.txt unfetchable | `app/robots.py` | `blocked / robots_disallowed` | **Yes**, both directions: 404 means unrestricted, 5xx means refuse |
| Out-of-scope admission | `app/executor.py` | `T-REFUSED` before any fetch | **Yes, since today.** Must-accept corpus is every `eval/dev-set.md` task plus the home page chips — written elsewhere, for other reasons; must-refuse is ours, held to the rule that every declared reason is exercised |
| Same-page evidence check | `app/verifier.py` | `failed / verification_mismatch` | **Yes, since today.** Positive and negative cases, including encoding, trailing slash, query string, scheme and subdomain |
| Ambiguous routing | `app/executor.py` | `unsupported / policy_refused` | **Yes.** `test_policy.py` has pinned the fixture operations since M1; today's addition extends the same two-sided corpus to the four promised records |
| Store path containment | `app/store.py` | artifact not served | **Yes.** `contains()` asserted true for a legitimate path and false for traversal |
| Planner proposal validation | `app/planner.py` | `failed / internal_error` | **Yes.** Refusals tested, and one test asserts a *correct* anchor-region proposal is accepted — added after the validator rejected a valid one |
| Vacuous verification (A11.7) | `app/verifier.py` | `failed / postcondition_unmet` | **Yes.** Both a claim-free postcondition (must fail) and a real one (must pass) |
| Budget ceilings | `app/provider.py` | `failed / budget_exhausted`, `blocked / provider_quota` | **Yes.** Exhaustion tested, and normal runs pass through the same checks daily |
| Egress / SSRF guard | `app/egress.py` | `blocked` | **Yes.** `test_egress_allows_declared_targets` names the three real hosts and asserts they pass, alongside the private/link-local refusals |
| Anchor ambiguity | `app/verifier.py` | `failed / verification_mismatch` | **Yes, since today.** Each of the three `AnchorAmbiguous` raise sites has both a disagreeing case that must refuse and a repeating-but-agreeing case that must resolve; the three are enumerated from the source by AST, so a fourth added without a case fails |
| Frozen-hash check (S-4.12) | `app/verifier.py` | `failed / verification_mismatch` | **Yes, since today.** The pass case is now deliberate rather than incidental — a frozen object must still match itself, key order must not matter, and every serialised field must change the digest |
| Reduction element cap | `app/reduce.py` | silent — no refusal at all | **No, structurally.** This is the OP-6 case: the cap has no failure status, it just shows the model less. `interactive_goal_term_over_cap` plus the quiet-outcome audit is the handle, and it only covers elements the goal *names* |
| Persistent-store requirement (A11) | `app/store.py` | process refuses to start | **Yes.** An unwritable directory and a non-mount are both asserted to refuse, and every other test in the suite constructs a working store |
| Provider model-alias refusal | `app/provider.py` | `SystemExit` at startup | **Yes, since today.** The marker test is split out as a pure function so the accepted case costs no provider call: every forbidden marker must be exercised, and the id we actually ship must not trip the rule |

## Where the corpus comes from

The first version of the must-accept list was written in the same sitting as the fix to the
control it tests, by whoever had just decided what the rule should be. It passed. It was
always going to pass — the same assumptions produced both halves, which is the same defect as
writing this inventory from memory, one level up. It has been replaced by every task in
`eval/dev-set.md` verbatim plus the home page's demo chips: sentences written for other
purposes, before the rule existed, and therefore able to disagree with it. The expectation
for each is read from the case's own `expected_terminal_status` rather than restated, so
DEV-13 — refused by robots *after* admission — correctly has to be admitted.

The must-refuse half is still ours and there is no honest way around that: nothing outside
this repo enumerates the acts we decline. Its guard is the coverage rule instead.

**"Every declared reason must be exercised" is the reusable part**, and it is what closed
three of the four gaps in the table above. In each case the missing half was the positive
one, because a refusal never asks to be explained:

| Control | Declared set, enumerated from the code | The half that was missing |
|---|---|---|
| Anchor ambiguity | the `AnchorAmbiguous` raise sites, found by AST | a label that repeats but *agrees* must still resolve |
| Frozen postcondition | every field of `Postcondition.to_dict()` | the object still matches itself, and key order does not matter |
| Model-alias refusal | `FORBIDDEN_MARKERS` | the id we actually ship must not trip the rule |

## What I am not claiming

"No" is not a prediction that the control is wrong. It is the statement that **if it were
wrong, this system has no way to notice**, and that is the property the two defects above
turned out to share.

One row is "No", and it is the one where the fix cannot be a test at all: the **reduction
cap** produces no verdict to test. It never refuses anything; it just shows the model less.
Its only handle is the quiet-outcome audit, which covers elements the goal *names* and
nothing else.

Three notes on how this table was built, because the method matters more than the rows:

- I wrote it from memory first and three rows were wrong — egress, the persistent-store
  requirement and routing all had two-sided coverage I had not credited. Checking each claim
  against the actual test file is what corrected them. An inventory written from
  recollection reproduces exactly the confidence it is supposed to audit.
- "Partly" meant the negative case was tested and the positive case was covered only
  incidentally, by real runs passing. That is weaker than it sounds: real runs stop covering
  it the moment they stop running. Three rows sat there; all three are closed above.
- Nothing in this table was added by reading the code for suspicious patterns. Both defects
  were found by a run failing for a reason that turned out not to be the run's fault.

Both of the first two notes are carried into `docs/m8-quiet-failures.md` §5 as the second
instance of that finding — the one where the confidence being audited was our own.

## The same defect with the sign flipped

While checking the table, a control turned up that had never fired at all. `T-DECLARED` is
defined at M1, is required by S-1.3 to be visible in the UI, and decides which runs count
toward the headline success rate — and nothing assigned it. Every run against a promised
record was reported as best-effort, and the support page said the four operations were "not
yet implemented" for a milestone after they shipped.

A control that never fires does not raise, does not refuse and does not break a test. It is
the same mistake `app/coverage.py` was built to prevent for terminal statuses, in a taxonomy
the ledger does not cover. Admission now derives the tier from the same promised-record list
the support page renders, so the two cannot disagree, and a dev case that reaches no
promised record fails the suite.

## Method, for the next one

The measurable question is not "is this control correct" but "what would have to be written
down for its being wrong to be visible". For anything that fails closed, that is a corpus of
inputs it must **accept**, ideally sourced from somewhere that had never heard of the
control. Everything else is asserting that a refusal refuses. And for anything with a
declared set of reasons, fields or markers, enumerate that set *from the code* and require
each member to be exercised — otherwise the set and its evidence drift apart silently, which
is how a rule ends up shipping with nothing behind it.

## Addendum, 2026-07-29 — two judgements the table did not have

The **same-page evidence check** row above has since been split by Amendment 26. It is now
two independent assertions — did the evidence come from a page the trace accounts for, and
is that landing reached from the plan's target by a recorded route — and both directions of
both are in `tests/test_m2_integration.py`, against a real browser and the fixture's
`/moved`, `/detour` and `/soft-moved` routes. `/detour` is the must-refuse half that the
old single check could not have: it reaches exactly the right final URL by a route no plan
named.

| Control | Where | Refusal it produces | Can we tell "right" from "always-on"? |
|---|---|---|---|
| Unknown URL scope | `app/verifier.py` | `unverified / postcondition_unmet` | **Yes.** Only our own compiler produces a scope, so this fires only on our own mistake — which is precisely what must not be able to buy a success. Asserted with the check recorded as *unevaluated* rather than as satisfied, and every legitimate scope exercised beside it |
| Login wall met mid-run | `app/executor.py` | `blocked / site_unavailable`, **by reclassification only** | **Yes, and the negative half is the point.** A visible password field shows a login form is *present*, not that content was replaced by one, so it may not end a live run — only correct the class of one already failing as `locator_not_found` / `postcondition_unmet`. Tested in all four directions: the wall is recorded, the run survives it, the reclassification fires for those two classes, and it leaves `budget_exhausted` alone |

The second is the more interesting entry in this whole table, because it is a fail-closed
control **deliberately denied the power to fail closed**. The rule this document is built on
is that a control which is always on and judging wrongly is indistinguishable from one
judging correctly. A wall detector that can end runs would be exactly that on unseen sites —
its wrong answers would arrive as `blocked`, which reads as caution. Restricting it to
re-labelling failures removes the state in which being wrong is invisible: it can now only
change *why* a run failed, never *whether* it did.

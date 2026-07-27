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
| Out-of-scope admission | `app/executor.py` | `T-REFUSED` before any fetch | **Yes, since today.** 12 must-accept + 14 must-refuse tasks, and a test that every declared reason is exercised |
| Same-page evidence check | `app/verifier.py` | `failed / verification_mismatch` | **Yes, since today.** Positive and negative cases, including encoding, trailing slash, query string, scheme and subdomain |
| Ambiguous routing | `app/executor.py` | `unsupported / policy_refused` | **Yes.** `test_policy.py` has pinned the fixture operations since M1; today's addition extends the same two-sided corpus to the four promised records |
| Store path containment | `app/store.py` | artifact not served | **Yes.** `contains()` asserted true for a legitimate path and false for traversal |
| Planner proposal validation | `app/planner.py` | `failed / internal_error` | **Yes.** Refusals tested, and one test asserts a *correct* anchor-region proposal is accepted — added after the validator rejected a valid one |
| Vacuous verification (A11.7) | `app/verifier.py` | `failed / postcondition_unmet` | **Yes.** Both a claim-free postcondition (must fail) and a real one (must pass) |
| Budget ceilings | `app/provider.py` | `failed / budget_exhausted`, `blocked / provider_quota` | **Yes.** Exhaustion tested, and normal runs pass through the same checks daily |
| Egress / SSRF guard | `app/egress.py` | `blocked` | **Yes.** `test_egress_allows_declared_targets` names the three real hosts and asserts they pass, alongside the private/link-local refusals |
| Anchor ambiguity | `app/verifier.py` | `failed / verification_mismatch` | **Partly.** Ambiguity is tested; nothing asserts that a label appearing legitimately in several places with the *same* value still resolves. A stricter ambiguity rule would fail correct runs and read as a mismatch |
| Frozen-hash check (S-4.12) | `app/verifier.py` | `failed / verification_mismatch` | **Partly.** Tamper is tested; the pass case is covered incidentally by every run rather than deliberately |
| Reduction element cap | `app/reduce.py` | silent — no refusal at all | **No, structurally.** This is the OP-6 case: the cap has no failure status, it just shows the model less. `interactive_goal_term_over_cap` plus the quiet-outcome audit is the handle, and it only covers elements the goal *names* |
| Persistent-store requirement (A11) | `app/store.py` | process refuses to start | **Yes.** An unwritable directory and a non-mount are both asserted to refuse, and every other test in the suite constructs a working store |
| Provider model-alias refusal | `app/provider.py` | `SystemExit` at startup | **Partly.** Moving aliases are refused in tests; that the pinned id is *accepted* is only proven by the service running |

## What I am not claiming

"Partly" and "No" are not predictions that those controls are wrong. They are statements that
**if one of them were wrong, this system has no way to notice**, and that is the property the
two defects above turned out to share.

One row is "No", and it is the one where the fix cannot be a test at all: the **reduction
cap** produces no verdict to test. It never refuses anything; it just shows the model less.
Its only handle is the quiet-outcome audit, which covers elements the goal *names* and
nothing else.

Three notes on how this table was built, because the method matters more than the rows:

- I wrote it from memory first and three rows were wrong — egress, the persistent-store
  requirement and routing all had two-sided coverage I had not credited. Checking each claim
  against the actual test file is what corrected them. An inventory written from
  recollection reproduces exactly the confidence it is supposed to audit.
- "Partly" here means the negative case is tested and the positive case is only covered
  incidentally, by real runs passing. That is weaker than it sounds: real runs stop covering
  it the moment they stop running.
- Nothing in this table was added by reading the code for suspicious patterns. Both defects
  were found by a run failing for a reason that turned out not to be the run's fault.

## Method, for the next one

The measurable question is not "is this control correct" but "what would have to be written
down for its being wrong to be visible". For anything that fails closed, that is a corpus of
inputs it must **accept**. Everything else is asserting that a refusal refuses.

# Every safety mechanism is also a hiding place

**Status:** a finding, not an incident. It generalises past the case that produced it, and it
is the reason one of this system's controls now audits the others.

---

## 1. The class

This system is built to fail closed. Each control was added for a good reason and each of
them works:

| Control | What it does when unsure |
|---|---|
| Abstain rather than guess (A2.2) | Refuses with a reason instead of producing a plausible answer |
| robots fail closed (A10) | Refuses to fetch when the rule cannot be shown to allow it |
| Refuse to start without a persistent store (A11) | Dies loudly rather than serving evidence it cannot keep |
| Postcondition frozen and hashed before browsing (S-4.12) | Cannot be moved to fit what was found |
| Vacuous verification fails closed (A11.7) | "Nothing failed" is not "everything passed" |

Every one of them converts an uncertain situation into a definite, quiet outcome. That is the
point of them. It is also the cost: **a wrong quiet outcome and a right quiet outcome look
identical from outside.** A refusal that was correct and a refusal caused by our own defect
produce the same status, the same explanation shape, and the same absence of a result.

So each control we add opens one more place a defect can sit undisturbed. This is not an
argument for fewer controls. It is an argument that the controls need something checking
them, because nothing else will: the louder failure modes get caught by the people they
annoy, and these ones annoy nobody.

## 2. The case that produced it

OP-6 — page through a category listing on books.toscrape — abstained on the planner-driven
path. Verbatim, from the run:

> The provided page view does not contain a 'next' button or pagination controls to navigate
> to the second page of the Nonfiction category.

That statement is true. The page has `<li class="next"><a href="page-2.html">next</a></li>`;
the *reduced view sent to the model* did not, for a chain of individually reasonable reasons:

1. the goal term `Nonfiction` matched the sidebar category list, so the sidebar became a
   candidate anchor region;
2. interactive elements were ranked by proximity to anchor regions, so all twenty sidebar
   links took top priority;
3. the remaining budget filled in document order with twenty product links and twenty
   identical "Add to basket" buttons — exactly sixty, the cap;
4. the pagination link is last in document order. It was dropped, counted only as one of
   `interactive_over_cap: 34`.

The model was shown a page with no pager and said so. **No policy check misfired. The
abstention mechanism worked exactly as designed, on an input that had already lost the
answer.**

The finding is not the ranking bug. It is that nothing downstream could tell this apart from
a page that genuinely has no pagination, because both produce the same honest refusal. From
the original session, kept as it was written:

> 這條是安靜的、而且是我們設計要它安靜。
>
> *(This one is quiet — and we designed it to be quiet.)*

We found it because we knew the expected answer for OP-6. On a held-out case nobody knows the
expected answer, and an abstention looks right forever.

## 3. What was built, not just written down

The reducer now records `interactive_goal_term_over_cap` as its own category rather than
folding it into a general over-cap count — a generic count cannot distinguish *we trimmed
some noise* from *we trimmed the answer*. But a reducer statistic is not a conclusion about a
run, and nobody reads reducer statistics on a run that refused.

So `app/suspicion.py` raises it to a run-level signal. Every run ends through one function,
`Executor._terminate`, and any run ending in a **quiet outcome** is audited against its own
trace before it is saved:

- `goal_named_element_dropped` — reduction discarded elements the goal itself names
- `anchor_region_dropped` — the region holding the value may never have been offered
- `refused_without_looking` — a page was fetched and then refused with no view produced
- `refusal_rule_not_quoted` — a robots refusal recorded without the rule that caused it

A run carrying any of these cannot be read as clean: the badge on the frontend says
`not a clean unsupported`, and the explanation itself — the field a person reads and an
evaluator quotes — is rewritten to begin `This outcome is NOT a clean unsupported:`.

Three properties make the signal worth something:

- **It cannot be routed around.** A test parses `app/executor.py` and fails if
  `terminal_status` is assigned anywhere except inside `_terminate`, which is the one place
  the audit runs.
- **It does not change any verdict.** The audit cannot make a run pass and does not demote
  one. It attaches what a reader needs; the taxonomy is untouched.
- **It weighs evidence honestly.** Verification never runs against the reduced view — it
  re-extracts from the full stored artifact (A7.4) — so trimming does not undermine a
  `no_result_verified` that was checked against an artifact. It is load-bearing precisely
  where nothing was checked against anything: an abstention, whose only input was the view
  that may be at fault. The audit encodes that distinction rather than flagging everything.

## 4. The limit of it, stated

This catches the case where **we** removed the answer. It does not catch an abstention caused
by something we have no counter for — a page whose relevant control is invisible to the
element selector, a term the goal never mentions. Those remain indistinguishable from correct
refusals, and the honest position is that the held-out set may contain some.

What the signal buys is a handle that is visible from outside without knowing the answer,
which is the only kind that helps on a held-out case. It is one handle, not a guarantee.

## 5. The second instance, where the confidence being audited was our own

The mirror of §1 turned up almost immediately, and it is worth recording because of *who*
it caught. `docs/m4-fail-closed-inventory.md` was written to list every fail-closed control
that cannot tell "on and right" from "on and wrong". Two things went wrong in the writing of
it, and both are the same failure the document is about:

1. **The inventory was written from memory, and three of its rows were wrong.** Egress, the
   persistent-store requirement and routing were all recorded as half-covered; all three
   already had two-sided tests. Checking each row against the actual test file is what
   corrected them. An inventory written from recollection reproduces exactly the confidence
   it is supposed to audit.

2. **The corpus that proved the fix was written by the session that wrote the fix.** The
   out-of-scope classifier was repaired and then given a hand-written list of tasks it must
   accept — composed by whoever had just decided what the rule should be. It passed. It was
   always going to pass: the same assumptions produced both. The list is gone. The
   must-accept corpus is now every task in `eval/dev-set.md` verbatim plus the home page's
   demo chips, sentences written for other purposes before the rule existed, which is the
   only reason they are able to disagree with it.

The general form: **a control that checks another control is a control, and inherits the
whole problem.** Self-written evidence is a quiet outcome in the same sense as a quiet
refusal — it looks like verification and costs nothing to produce. The only structural
defence found so far is provenance: the inputs an assertion is made of should come from
somewhere that did not know about the assertion.

Two mechanisms now enforce that where they can:

- **Corpus provenance.** The accept half comes from outside the control's own session; the
  refuse half cannot (nothing external enumerates acts we decline), so it is held to the
  coverage rule instead.
- **Every declared reason must be exercised by some case.** Written for the refusal reasons
  and then applied to three more places where only half the evidence existed: every
  `AnchorAmbiguous` raise site in the verifier (enumerated by AST, so a fourth one added
  without a case fails), every field of the frozen postcondition, and every forbidden model-id
  marker. In each case the *positive* half — the anchor that repeats but agrees, the frozen
  object that still matches itself, the pinned model id that must not trip the alias rule —
  was the half missing, because a refusal never asks to be explained.

### The same defect with the sign flipped

A control that never fires is the other end of this. `T-DECLARED` was defined at M1, is
required by S-1.3 to be visible in the UI, decides which runs count toward the headline
success rate — and was assigned by nothing. Every run against a promised record was labelled
best-effort. The frontend was underreporting the system by an entire milestone, and no test
noticed, because a tier that is never assigned raises nothing and breaks nothing.

That is the same mistake `app/coverage.py` exists to prevent for terminal statuses: at M1 a
hard gate appeared to pass while being unreachable. The ledger covers statuses and failure
classes. It did not cover tiers.

## 6. The defect that this class already cost us once

Recorded in `docs/m8-credential-exposure.md` §5: arbitrary file deletion plus arbitrary file
read, live since M2, in a product whose selling point is its safety posture. 107 tests did
not catch it. What caught it was being asked to prove a boundary, and writing the test that
proved it did not hold.

Same shape as this one. A control that is trusted and never independently checked is
indistinguishable from a control that works.

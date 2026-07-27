# M3 — The planner, and what happens when it is wrong

**Date:** 2026-07-27 · **Gate (§13 M3): the mechanism is in place and demonstrated.**
Recoveries are cross-family and carry a named diagnosed cause; retry and recovery are
distinguishable in the trace; the exploration/recovery budget split is enforced by the
provider adapter rather than by discipline at call sites.

Not yet closed: the four M3-due failure classes have not all been produced by a run, so the
coverage gate still reports them overdue. That is the honest state and it is visible on
`/coverage` rather than described here.

---

## 1. What the model is allowed to do

Propose one action at a time against a reduced view. That is all.

- It cannot write the postcondition — that is frozen by code before browsing, exactly as at
  M2, and the planned path and the deterministic path freeze the *same object*.
- It cannot mark anything verified. `succeeded_verified` appears in one module and the
  planner is not it.
- It cannot widen the action allow-list, act on a ref that was not in the view we sent, name
  a diagnosis outside the closed set, or ask for a coordinate click. Each of those is
  refused at the boundary and recorded — never repaired into something plausible.
- **It does not report the answer.** When it emits `finish`, the plan's deterministic read
  step produces the candidate, and the verifier re-extracts independently from the stored
  artifact. A model that could both act and report would be grading itself.

The result: a planner-driven run and a scripted run reach the same status through the same
verifier against the same frozen postcondition. They are comparable because only the *route*
differs.

## 2. Recovery, demonstrated rather than asserted

`MU-6` is now implemented — a cookie banner that covers the pager on `/browse`. It is a
markup transform, so the correct answer is unchanged and only the route to it is blocked.

A planner-driven run on that seed, verbatim from the trace:

```
 7. click     FAIL  click e9 — to view page 2 I must click Next        [-→F2]
 9. note      ok    Model call (recovery) for step 2
10. click     ok    click e10 — the previous attempt failed due to an
                    overlay, so I will dismiss it first                [F2→F1] cause=obscured_by_overlay
13. click     ok    click e9 — e9 is the Next button                   [-→F1]
```

Every element the gate asks for is in those four lines: the failure, a **named cause from
the closed set** (`obscured_by_overlay`, diagnosed by asking the page what is true, not by
reading the exception text), a **cross-family transition** (F2→F1) recorded on the entry
itself, and a call drawn from the **recovery reserve** rather than the exploration budget.

A repair that stays in the same family is recorded as `retry` on the same fields. Neither is
inferred later from the shape of the trace; both are decided when the step is taken.

## 3. Where the planner is unreliable, and why that is contained

Recorded because it is the finding, not a caveat.

**The planner does not reliably recognise that the goal is met.** On the pagination task it
reached page 2, extracted the rows, and then clicked `Next` again — overshooting to page 3
and continuing until the step budget stopped it. Two earlier variants of the same problem
were fixed first (see §4), and this one remains.

What matters is what happens next. The postcondition froze `page: 2`. An overshoot produces
an artifact showing page 3, the verifier compares the pager against the frozen input, and
the run fails as `verification_mismatch`. **The model's unreliability turns into a loud
failure rather than a confident wrong answer** — which is the property the whole design
exists for.

Two bounded, honest options for M4: feed the frozen inputs into the prompt as a progress
statement, or terminate the loop at the first successful extraction. Both are prompt/loop
changes, neither weakens the postcondition, and both are measured against the same gate.

## 4. Three defects found by running it, all ours

**The reduced view hid its own state.** Form fields were sent without their current value,
so a filled field looked identical to an empty one and the planner refilled it. Then anchor
regions were offered without a visibility check, so the planner was handed `hidden` page
blocks and told "not yet rendered" about something that would never render.
`reduce/v1.1` and `v1.2`.

**An action whose result the model never saw.** `extract` succeeded and returned nothing to
the history, so the planner could not tell a step that worked from one that did nothing, and
repeated it until the step budget ran out. The observed text is now fed back — the model
sees *that* it worked, and still does not get to report the value.

**The required-action check could not see a planner-driven click.** The postcondition
declares `click #next`; the planner works in refs. Every planned run failed as
`required_action_skipped` while having taken exactly the right action. Refs are now resolved
to a durable identity — id, name attribute, visible text — and the check matches against all
of them. This is the same class as the M2 finding: two correct components with no agreed
vocabulary between them.

And one found by the product refusing to guess: the task
`"…seed mu6-overlay, use the planner"` routed to **two** operations, because the seed name
contains the word "overlay". Abstain-don't-guess reported it instead of picking one. Run
directives are now stripped before routing — they describe *how* to run a task, not what is
being asked.

## 5. Budgets, and a ceiling that had never been enforced

The provider adapter is the only place a model call happens, and everything bounded is
bounded there: per-call input cap (over the cap, the call is **not sent**), cumulative input
and output budgets per run, output capped per call because output is the expensive half,
RPM pacing against the measured ceiling, and the exploration/recovery split — exploration
cannot consume the recovery reserve, or a run dies before it can demonstrate the
self-correction it is being graded on.

Added alongside: **persistent provider spend accounting**. A8.10's USD 5 self-approval
ceiling existed as a number a person was holding in their head, with nothing at runtime
counting against it. It is now stored in the volume-backed database, checked **before** each
call, and exceeding it is a refusal rather than a warning. Measured cost per planned run so
far: **$0.0010–$0.0019**.

## 6. What M4 inherits

- The coverage gate will fail until `provider_quota`, `provider_error`,
  `token_budget_exhausted` and `context_budget_exceeded` have each been produced. They are
  reachable now; none has been walked.
- Goal-completion detection (§3) is the first thing a real site will punish.
- The postcondition for a real-site task still comes from code. Nothing here synthesises one
  from an arbitrary request, and pretending otherwise is what M4 must not do.

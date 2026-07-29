# ENG work order 2 — one silent success, four page defects, four in-flight UX gaps

The same independent reviewer ran the deployment a second time at `d844a9a7e9c3`. **Ten of the
eleven first-round items are fixed and stayed fixed** — the fixes were more thorough than the work
order asked for, and nothing regressed.

The one item that was *added* in that round is the problem. Full report: `acceptance-report.md`,
second round at the top. Ruling: **Amendment 28** in `docs/task1-spec.md`, acceptance **A-84 / A-85**.

Item 1 is the only one that matters if you run out of time. Do it first and do it alone if
necessary.

---

## 1. OP-5 returns `succeeded_verified` for a question it never answered (critical)

Send `eval/dev-set.md` DEV-04 verbatim:

> On the Wikipedia article for Apple Inc., expand the first collapsed box at the foot of the page and
> tell me **its title and the label of its first row group**.

The frozen goal comes out as *"expand collapsed box 1 and report that it is no longer collapsed."*
The only claim is `still_collapsed`. Terminal status `succeeded_verified`, counts as success. DEV-05
(*"how many entries are in its first row group"*) does the same. **Neither answered the question, and
the answer is in the stored artifact** — the reviewer pulled `art_c8330f17bc11`, 2,523,585 bytes,
hash verified, and read `Products` / `Hardware` / `Mac` out of the `navbox-group` cells.

**Cause, precisely.** `app/executor.py:2148-2166`: `GROUP_PHRASE` matches a *named* group (`the
'Hardware' group`, `the Hardware group`). Both canonical cases name an *ordinal* one (`its first row
group`). The regex misses, `group` stays empty, the `ClaimSpec("group", …)` on line 2166 is never
appended, and the postcondition freezes with the state-transition claim alone.

**Why nothing caught it.** `asked_for_parts` already exists, is parameterised over eleven task shapes
in `tests/test_asked_for_parts.py`, and enforces exactly this rule — **and it is called from
`_plan_generic` only** (`app/executor.py:2876`). No other planner was ever reconciled against it. The
verifier cannot help: it compares claims to artifacts (`app/verifier.py:475-505`) and never sees the
task text. So the rule was written, tested, and pointed at one of its callers.

`_plan_wiki_expand` is the only declared planner with this exposure — the others (`_plan_book_detail`,
`_plan_book_category`, `_plan_wiki_sort`) claim a fixed superset and can over-claim but not
under-claim. **Check that statement rather than trusting it**; it is the whole scope argument.

**Do — in this order.**

1. **The rule, applied (A28.2, A-84).** Reconcile every task-derived postcondition against
   `asked_for_parts`. Any asked-for part with no claim of its own becomes a `LOCATED_LABEL` claim —
   the same weaker binding `_plan_generic` already uses and A13.2.3 already permits. That is the fix:
   a part that then fails to bind produces `partial`, which is loud and never counts as success. A
   silent success becomes either a real answer or a visible failure, and no new relation is needed.
2. **Only then, if time allows:** teach `GROUP_PHRASE` the ordinal form (`its first row group` →
   `navbox-group` cell *n*) and a count form for DEV-05, so those two cases resolve deterministically
   instead of depending on the model emitting an `extract`. Higher fidelity, more risk, second.

**Done when:** a test drives both canonical task strings and asserts the frozen postcondition carries
a claim for the asked-for value; and a run that binds only `still_collapsed` terminates `partial`.
**A test that asserts `_plan_wiki_expand` produces two claims when the group is named is the defect
again** — that path already worked.

**Also, and separately (A-85):** `app/records.py:54` publishes the OP-5 promise on `/support` as
*"Expand a collapsed box and extract a value not visible beforehand"*. Until item 1 lands, that string
has to say which of the two it currently delivers — every published OP-5 result outside the code
already does (README, `README.zh-TW`, both analysis reports, the grader guide). The page is the last
one still overstating it.

**Do not** narrow the promise instead. §4 promises a verified value; A25.3 forbids dropping an
asked-for part on *any* tier. Rewording leaves the violation in place and removes the evidence of it.

## 2. The homepage says the example buttons are the pre-executed tasks; 3 of 4 are not (medium)

| Button | Pre-executed row | Same? |
|---|---|---|
| `Search the fixture catalogue for lantern` | identical | yes |
| `Is any product **in the fixture catalogue** priced over £100?` | `Is any product priced over £100?` | **no** |
| `Read page 2 of the **fixture** browse listing without clicking next` | `Read page 2 of the browse listing…` | **no** |
| `Dismiss the overlay on the **fixture** gated page…` | `Dismiss the overlay on the gated page…` | **no** |

This is a side effect of the round-1 de-dup fix: the demo strings were changed so the buttons stop
evicting them, and the sentence that says they are the same tasks was not changed with them. A grader
clicks a button, gets a near-identically-named row, and believes they re-ran the demonstration.

**Do:** either make the strings match again (the flag-based selection means they no longer need to
differ) or say the buttons are *variants* of the pre-executed tasks. **Done when:** a test compares
the rendered button strings against the seeded demo tasks and fails when they diverge.

## 3. "Run at startup" is not true, and the demos are from an older, weaker verifier (medium)

`/healthz` `uptime_seconds` 145, homepage `Runs this generation 0`, `Restarts 0` — and the demo
evidence is dated **2026-07-27**, with `/coverage` showing `run_505c6ac2b811` as `succeeded_verified`'s
first run across an unknown number of restarts. They are **seeded once and pinned**, not run at
startup. `app/templates/index.html` and `docs/grader-guide.zh-TW.md` L56/L60 both say startup.

Worse: open `run_505c6ac2b811`. **Four gates** — `postcondition_frozen`, `artifact_available`,
`artifact_source_matches_plan`, `required_actions_present`. Current runs show six or seven, plus
`N of M claims were independently re-resolved`, plus `artifact_origin_is_the_named_site`,
`artifact_source_is_accounted_for_by_the_trace`, `landing_explained_from_the_plan_target`, and
`freshly derived` locator badges in the trace. **The runs a grader is told to open first demonstrate a
weaker verifier than the one we ship**, with nothing on the page saying they are from an older build.
That row also shows a red `empty_state not verified / locator_not_found` on a `succeeded_verified`
run — correct (optional claim), unexplained on the page.

**Do:** re-seed the demonstrations on the current build so they show the current gate set — that
fixes the wording problem too. If re-seeding is not possible, say `seeded once and pinned` and print
the build each demo row came from. Either way, label the optional-claim red line as optional.

## 4. The `inspect` column is off-screen at the default width (medium)

Measured: runs-table container `clientWidth` **922**, `scrollWidth` **1022**, `inspect` right edge at
1022, `scrollLeft` 0 on load. **The link is invisible until you scroll the table sideways**, and the
dark theme gives no scroll affordance. The `Task` column is 245px, truncating to ~40 characters.

Both guides open with *"scroll to the runs table and click into a run"*. That is the first instruction
a grader follows and the target is hidden. Grader-guide step 8 also asks for a task-string comparison
against `/support`, which truncation makes impossible without opening each row.

**Do:** make the row itself clickable, or pin `inspect` with `position: sticky; right: 0`. Put the
full task text in a `title` attribute either way.

## 5. `Run` needs two or three clicks (low — first round's N10, still open)

All three of this round's submissions needed two or more clicks. Six for six across two rounds now.
The markup still looks correct, so a synthetic-click artefact is still the likely explanation, but at
six for six it is worth one human click-through. If it reproduces by hand, disable the button and show
`submitting…` on first click.

---

## In-flight UX — four gaps, all in the same place

The reviewer watched a 25-step run to `budget_exhausted`. **First paint is genuinely good**: the
action trace is already rendered to the current step, `Execution: still running`, `Steps 2 of 25`.
The problem is that **only the heading line advances after that**, so the page shows `Step 11` in the
heading and `Steps 2 of 25` in the Budget panel simultaneously, with nothing marking which is live.

1. **`No claim was produced.`** appears in the Claims panel *during* the run. It reads as a verdict
   and means "not yet". Use `No claim yet — the run is still going.` while running.
2. **`Step 11: Snapshot captured: step-2`** puts two different meanings of "step" in one line
   (execution count vs. plan-step name). Drop the artifact's internal name from the progress line.
3. **The progress line carries neither elapsed time nor the step budget.** The most distinctive
   behaviour in this system is the fail-closed step cap, and a run that ended `budget_exhausted` never
   once signalled that it was approaching it. `Step 11 / 25 · 8s` costs two fields and says both what
   it is doing and that it is running out.
4. **`Waiting…`** does not say what is being waited on — queue, browser context, or model. Split it
   at least into "waiting for a browser context" and "waiting on the model".

Either make the whole panel set advance, or mark the live fields explicitly. Do not leave two
contradictory step counts on screen.

*(Not verifiable this round: the reviewer never saw the `queued` state because concurrency was never
saturated, so whether queue position is displayed is unconfirmed.)*

---

## The standing rule, restated because item 1 is what it is for

Round 1's rule was *assert the rendered page against a value the code derives, not against the
sentence*. Item 1 needs the next one: **when a rule is written, enumerate its callers.** `asked_for_parts`
was correct and well tested. It was wired to one of the places that needed it, and the audit that
would have found the others was never run. When you land A-84, the test that matters is the one that
asserts *every* postcondition-compiling path reconciles against it — not the one that asserts the
parser works.

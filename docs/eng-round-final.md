# ENG work order — five page-level fixes found by an independent reviewer

An independent reviewer operated the deployed site through the browser only, without reading any
product code, and found eleven things not on our known-issues list. Eight were documents describing
something that is not true on the page. **The documents are already fixed.** These five are the ones
that need code, and every one of them is the same defect family the analysis report's §5.4 already
names: *a page describing itself in words that nothing checks.*

Full report: `acceptance-report.md`. Every item below is reproducible against
`https://wf-agent.zeabur.app` at `7bfa5d2c3185`.

Order matters — 1 and 2 are the ones a grader hits in the first ten minutes.

---

## 1. The homepage promises a badge and a date that never render (high)

`app/templates/index.html:165-173` tells the reader:

> Rows badged `pre-executed` were run at startup … find them by the badge rather than by position.
> Their evidence is **pinned** … so each one shows the date its evidence was captured.

**Zero rows carry the badge, and no row shows a capture date.** `pre-executed` appears twice in the
whole page and both are in this paragraph; `evidence captured` appears zero times.

Cause: `_distinct_by_task` (`app/server.py:209`) keeps one row per distinct task, newest first. The
demo chips carry the *same task text* as the startup runs, so the first visitor who clicks one
evicts the demonstration row and its badge with it.

This was defect 15's fix. **The fix replaced one stale sentence with another stale sentence, and
nothing checked the new one either.** That is worse than the original, because it is the second time.

**Do:** make the de-dup keep the pre-executed row *in addition to* the newest live run of the same
task, and render the badge plus its capture date on it. If that is too invasive, the acceptable
alternative is to render badge and date wherever the row does survive and rewrite the paragraph to
claim only what the template can produce.

**Done when:** a test asserts the rendered homepage contains at least one row bearing the
`pre-executed` badge *and* a capture date, and that the assertion still holds after a live run of the
same task has been recorded. **A test that only checks the paragraph text is the defect again.**

## 2. The escape hatch the same paragraph promises does not exist (high)

That paragraph ends with *"Every run is still listed at `/api/runs`"*. **`GET /api/runs` returns
HTTP 405** — the route is POST-only (`app/server.py:306`). The run-detail footer's `all runs` link
points back at the same de-duplicated table. So a reader has no path at all to the full list, which
is precisely the justification the paragraph gives for de-duplicating.

**Do:** add `GET /api/runs` returning every stored run, newest first, as JSON — id, task, tier,
path, terminal status, failure class, counts-as-success, steps, duration, whether it was
pre-executed, and its detail URL. Paginate if you like; say so in the response if you do.

**Done when:** `GET /api/runs` is 200, contains more rows than the homepage table, and a test asserts
both. The de-dup rationale is only honest while this endpoint answers.

## 3. `/coverage` states the opposite of what is true about itself (medium)

`app/templates/coverage.html:38,46`: *"This counts this deployment since its last restart"* and
*"Storage here is ephemeral, so a redeploy resets this table."*

Both are false. The ledger is written through `Store` onto the mounted volume — `/healthz` reports
`storage.persistent: true`, `on_mounted_volume: true` — so it **accumulates across restarts and
redeploys**. A reader who believes those sentences reads a long "never produced" list as *we just
restarted* rather than as *this path has never once been driven in production*, which inverts the
only conclusion the page exists to support.

**Do:** say it accumulates across deployments, and say which store it lives in.

**Done when:** a test asserts the page does not claim the ledger resets, ideally by asserting against
the same `storage.persistent` value the health endpoint reports rather than against a string.

## 4. `/support`'s L-1 remediated entry publishes the wrong failure class (medium)

`app/limitations.py:58,70` publishes the remediated phrasing as ending `failed / budget_exhausted`.
Run it: it ends **`failed / verification_mismatch`** (25 of 25 steps). The prose explanation matches
the trace; only the label is wrong.

This one matters more than its size. `eval/limitations_check` re-ran all seven entries and reported
all seven reproduce. It did not catch this, so **the checker compares at a coarser grain than the
entry publishes** — a check that is looser than its own claim, which is family one in §5.4.

**Do:** correct the class to `verification_mismatch`, and extend `eval/limitations_check` to compare
`failure_class` as well as `terminal_status`. If an entry deliberately does not pin a class, let it
say so explicitly rather than leaving the field to go unchecked.

**Done when:** the checker fails against the current published text, then passes after the
correction.

## 5. Run detail shows the negative half of a binary only (low)

`app/templates/run.html:15-17` renders `does not count as success` when the run does not count, and
nothing when it does. The guides tell the reader to trust that field rather than infer from the
status word — and on this page there is nothing to trust. Render the positive badge too.

---

## Not asked for, recorded so it is not lost

The reviewer reported the `Run` button needing two or three clicks before submitting. The markup and
handler look correct (`index.html:27-38,126`), the chips are `type="button"`, so this is most likely
an artefact of synthetic clicks. Worth one human check. If it reproduces by hand, the cheap
mitigation is disabling the button and showing `submitting…` on the first click.

## The standing rule for all five

Every one of these is a sentence about the product that nothing verified. When you fix each one,
**the test must assert the rendered page against a value the code derives**, not against the
sentence. A test that pins the prose is how the first three of these survived a review that was
specifically looking for them.

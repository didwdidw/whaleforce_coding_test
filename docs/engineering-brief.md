# Engineering Session — Opening Brief

## Your role

You implement `docs/task1-spec.md`. **The spec governs.** Read it yourself — this brief does not
repeat it and does not override it.

You may **stop and discuss** at any time: a requirement that turns out to be impractical, a design
you believe is better, an assumption in the spec that reality contradicts. Raising these is expected
and welcome.

You may **not decide unilaterally**. If a spec requirement is in your way, the move is to stop and
ask, not to reinterpret it, work around it, or implement "the spirit of it". A silently reinterpreted
requirement is worse than a blocked one, because acceptance will grade against the written spec.

If you change the spec's meaning, that is an amendment in §16 — proposed by you, approved by the
product owner, never written by you alone.

## What you will never be given

**Validation and test case content.** Ever. You get the dev split (`eval/dev-set.md`), an aggregate
score, and a `failure_class` histogram. Nothing else. Do not ask for the cases, do not try to infer
them from scores, and do not tune against the histogram case-by-case. The split exists so that the
score means something; asking for it is asking to destroy the only measurement we have.

## Where to start

### M0 — Preflight, from the deployed environment (not your laptop)

This is a **report, not code**. Deliverable: a written preflight report containing

1. RAM headroom: one browser process + 2 contexts + the app, under load, on the chosen tier.
2. Reachability of `en.wikipedia.org`, `books.toscrape.com`, `www.sec.gov` **from the deployment IP**,
   with status codes. Cloud IPs get treated differently from residential ones — this is the point of
   the check.
3. Re-verification of the policy facts in spec §3.4 (robots rules, SEC's stated limits).
4. The account's actual Gemini rate limits, read from the console — the docs do not publish them.
5. Token and USD cost per run on three page shapes, and the requests-per-day feasibility arithmetic
   (Amendment 7.8). Say plainly whether a full eval round fits in one day.
6. Pinned target pages for OP-4…OP-7, and which OP-5 variant you are using.

**If anything in M0 fails, stop and report.** Do not substitute a site, do not engineer around a
block, do not shrink a budget to make the numbers fit.

### M1 — Walking skeleton, deployed

Deliverable: a **public URL** where a task can be submitted, runs against the fixture with **no LLM
in the loop at all**, and shows progress plus a step trace. Queue and 429 behaviour work. Nothing is
verified yet, nothing is intelligent yet.

Build this before anything clever. Deployment, the browser lifecycle, the queue, and the trace store
are where time actually disappears, and every later milestone rides on them. A brilliant agent that
is not deployed scores nothing — the graders test the deployed system.

## Traps — where "looks right but is wrong" gets built

- **Verifying against the trimmed snapshot.** The reduced view goes to the model; verification must
  re-resolve anchors in the *full* stored artifact (A7.4). Verifying against the trimmed view makes
  verification circular and it will pass everything.
- **Letting the model hand you anchor and value together.** The anchor must be independently
  re-resolvable by code that never sees the model's answer. If the only thing proving the value is
  the same generation that produced it, nothing is verified.
- **The second table.** The S&P 500 article has two sortable tables with overlapping column
  semantics. Anchors scoped by header text alone will match the wrong one and return a completely
  plausible wrong answer.
- **Numeric vs lexicographic sort.** Verify the order *the page produced*, not the order you would
  compute. Getting this backwards produces confident nonsense on CIK and GDP columns.
- **Adjacent labels.** On a books.toscrape product page, "Price (excl. tax)" and "Price (incl. tax)"
  are adjacent rows and frequently carry identical values. Label→value binding has to be exact, and
  a passing test on this page proves less than you think unless the labels differ.
- **Absence without a coverage anchor.** "I looked and didn't find it" is `unverified`, never
  `no_result_verified` (Amendment 3).
- **A retry wearing a recovery costume.** Same strategy family with a reworded prompt is a retry.
  Recovery is a *cross-family* transition driven by a named diagnosed cause.
- **Exploration eating the recovery reserve.** If the budget split isn't enforced, runs die before
  they can demonstrate self-correction — and self-correction is the headline graded mechanism.
- **Memory write-back from an unverified run**, or a memory hit that skips verification. Poisoned
  locator memory is worse than no memory.
- **Fixture on localhost.** It will trip the egress guard, and the tempting fix — an allow-list hole —
  destroys the security claim. Separate public hostname (S-2.8).
- **`partial` and `unverified` leaking into success.** Check every aggregation, every chart, every
  API field, and the copy on the page.
- **Injection detection by keyword.** Matching "ignore previous instructions" catches nothing real.
  The defence is structural: goal and policy outside model-mutable state, action allow-list,
  navigation origin policy.
- **Free-tier quota burned by your own iteration.** Your development loop draws on the same daily
  budget as the eval. Plan for it, and use the demo/eval credential separation from the start.
- **First impression is a cold start.** A grader's very first request may sit behind container and
  browser startup. Pre-executed runs on the homepage are not decoration; they are the difference
  between "slow" and "broken".

## Stop and ask — do not decide these yourself

1. **Any paid resource, any recurring cost.** Bring alternatives and a number.
2. **M0 showing the free tier cannot cover a full eval round.** Report the arithmetic and the
   paid-tier cost; the spend decision is the product owner's.
3. **Any site unreachable or blocked from the deployment IP.** Do not substitute another site.
4. **Changing the pinned model**, using a `latest` alias, or any preview model.
5. **Any change to** promised records, the status taxonomy, the strategy families, the hard gates, or
   the definition of `verified`.
6. **Anything that would make a gate pass by weakening it.** If the only way through is to lower the
   bar, the correct outcome is a failing gate and a conversation.
7. **The OP-5 variant**, if the collapsible target turns out to be unstable. The spec names a
   fallback (S-3.4) — confirm which one you took.
8. **Dropping a promised record.** Allowed, and sometimes correct — but it is a product decision, and
   it must be removed from the support matrix and README at the same time.

## Working conventions

- Log every prompt verbatim to your own file under `prompts/`, per `CLAUDE.md`.
- Commit at real milestones — not once per action, not one squashed lump at the end. The commit
  history is graded as evidence of real incremental development.
- Build in milestone order (§13). Do not start a milestone with an earlier gate unmet.
- When you cut scope, cut in the pre-committed order (S-13.1) and say so out loud.

# Analysis report — Task 1

Runtime performance, cost, scalability, and how correctness is verified. Written to be checkable:
every number here either comes from a committed measurement file or is marked as an estimate with
its method.

Numbers carry their qualifier. A figure without the conditions it was measured under is not a
measurement, and several figures below are deliberately reported as ranges or per-path splits
because a single mixed number would describe neither case.

---

## 1. What was measured, and on what

| | |
|---|---|
| Host | Zeabur on a self-hosted Ubuntu 24.04 box running k3s. `nproc` 2, `free -m` total **3,723 MB**, swap 1,987 MB provisioned. Swap was observed at a flat 102 MB during a scored round with **zero growth**, which was M0's pass condition |
| Browser | One Chromium process, two contexts. Not two processes — see §4 |
| Model | `gemini-3.1-flash-lite`, pinned. Never a `latest` or preview alias — a moving model makes every earlier measurement describe a system that no longer exists |
| Build under measurement | `e1d13cae4926` for `r1`, `aa1ee6c5d5eb` for `r2`, **`e82cacb9e809` for `r3` and `r4` — the frozen submission build, and where the headline and held-out numbers come from** — `427cd96` for the load measurements; each result file carries its own |
| Measurement files | `eval/results/`, `docs/m0-*`, `docs/m1-report.md`, `docs/m3-model-comparison.md` |

---

## 2. Runtime performance

### 2.1 Latency

From `r1`, inside the deployment, across 25 real cases. Reported per path, because a mixed figure
describes neither.

| | Deterministic path | Model-driven, declared (n=12) | Model-driven, experimental (n=10) |
|---|---|---|---|
| End to end, median | **0.16 s** | **5.85 s** | **12.18 s** |
| End to end, p90 | 0.16 s | 13.07 s | 27.73 s |
| End to end, max | 0.16 s | 16.43 s | 30.29 s |
| Time to first result, median | — | 5.13 s | 12.13 s |
| Provider time, median | **0.00 s** | 1.65 s | 3.74 s |
| Queue wait, median | 0.01 s | 0.01 s | 0.01 s |

Three readings worth taking off this rather than off the headline:

**The experimental tier costs about 2.1× the declared tier.** A declared record runs against a frozen
plan: the model is asked what to do next, not what the page is. An experimental run has to work out
the shape of a page nobody described — more calls, more captures. That is what the breadth costs, and
it is paid per run rather than amortised.

**Provider time is a minority of wall clock — 28% of the median declared run, 31% of the median
experimental one.** The rest is browser: navigation, waiting for a document to settle, and the
captures. Optimising the model would not move this product's latency much.

**Verification is not the expensive part, and that is a real finding.** Deterministic re-resolution
inside the stored artifact does not appear as a distinguishable term in any of these medians — it is
lxml parsing and XPath evaluation over a document already in memory, tens of milliseconds against a
5–12 s run. The whole design rests on doing that check, and the check is close to free. The costs
this design actually pays are in **storage** (§4) and in **abstentions** (§3), not in latency.

### 2.2 Cold start

Two numbers, because they answer different questions and conflating them was a defect we corrected:

| | Measured |
|---|---|
| **Deploy to usable** — a push landing, the container building, the app answering | **112–176 s** |
| **Interruption to a user already using it** — the window where requests fail rather than queue | **12–23 s** |
| **First request to a cold-but-deployed container** | **not measured** — see below |

The second number is the one that matters to a grader, and it is an order of magnitude smaller than
the first. It was measured externally rather than from inside the process being restarted — a
process cannot time its own unavailability. Six readings are committed
(`eval/results/coldstart-deploy-*.json`); the most recent, across a push of ten commits, was **141.1 s
to a completed task with 16.3 s of outage**. Most of the spread across the six is the platform's
build queue before the container swap, which is why this is a range and not a figure.

**Cold arrival is not measured, and the reason is stated rather than the number estimated.** It needs
an idle window long enough for the platform to evict a container that nothing has touched, and every
window this project had was occupied by a deploy or a scored round. We also never established that
this deployment goes cold at all. An estimate here would be a guess wearing a measurement's clothes,
so the row says *not measured*.

Our own assumption about this was wrong, and the measurement is what corrected it: A11.2 assumed cold
arrival would dominate the wait a grader feels. Five readings showed the build queue does. That is
recorded as an assumption overturned by our own data rather than quietly dropped.

The mitigation is design, not money: the homepage carries pre-executed runs, including failures, that
are inspectable with no container work at all (S-11.5). A grader's first impression is never an
unexplained spinner. We accepted cold start rather than paying to avoid it.

### 2.3 Throughput and load

From `load-local-427cd96.json`, on the deterministic path with no model call in the loop.

| | Measured |
|---|---|
| Configured capacity | concurrency 2, queue depth 2 |
| Saturation onset | a burst of **5** is the first to be refused |
| Sustained throughput | **430 runs/minute** over a 45.7 s window, 6 clients, 328 completed, 421 refused at admission |
| Queue wait under that load | median 0.23 s, max 0.47 s |
| Run duration under that load | median 0.21 s, max 0.50 s |

**That throughput figure is not a capability claim and must not be quoted as one.** These runs take
~0.2 s, so the queue drains underneath a burst while the burst is still arriving. A model-driven run
takes 5–30 s, nothing drains during a burst, and refusal therefore begins at the first submission
past `concurrency + depth` — four in flight. The saturation point of 5 is a property of the workload
as much as of the queue, and the result file says so in its own text.

**The 429 is a designed state, not an error page.** Firing several runs back-to-back is stated
grader behaviour (S-11.10b), so a rejected run is `blocked / queue_full` carrying `Retry-After`, and
it reads as terminal on the API, on the run page and on the health endpoint alike. Nothing is left
hanging until it times out, and no request is silently dropped. An unbounded queue on a 4 GB box is
how a demo becomes an outage.

### 2.4 Memory — the binding constraint

| | |
|---|---|
| Peak observed under load | **2,320 MB** of 4 GB |
| Swap | flat at 102 MB — the system did not fall into swap under measurement |
| Headroom | **1,457 MB available at the peak**, with two browsers up — measured by sampling host `free -m` every 10 s from 30 s before the round's restart to 5 minutes after. Baseline 1,795 MB used; back to 1,836 MB within a minute of the round ending and flat for five, so the memory is returned rather than merely not exhausted |

Memory, not CPU and not money, is what caps concurrency here. Two browser **contexts** in one process
rather than two processes is the decision that makes concurrency 2 fit; the measurement is why the
number is 2 and not 4.

---

## 3. Cost

### 3.1 Measured

| | |
|---|---|
| Median cost per model-driven run | **USD 0.0019** |
| Runs on the deterministic path | **USD 0** — no model call |
| Totals, per round and cumulative | **[`docs/spend-ledger.md`](spend-ledger.md)** |

**Every total in this project is in one generated file, and this document quotes none of its own.**
Three places used to carry a spend figure; all three went stale on the same day and one of them —
*"total provider spend across every scored round"* — was false rather than merely old, because it
predated a round. `python -m eval.spend_ledger` regenerates the ledger from the readings and the
round provenance, and `--check` fails when the committed copy is out of date, so the next stale total
is a test failure rather than something a reader finds. The per-round breakdown, including which
split cost what, is there.

Every figure there is billed spend. A ledger that counts free-tier usage at notional prices measures
something real but it is not money, and treating the two as the same nearly blocked our public demo
after ~125 runs having spent nothing. Both are tracked; only one is called cost.

### 3.2 What the number depends on

The figure is only valid under the conditions it was taken in, and each of these invalidates it if
it changes:

- **Prices**: USD 0.25 / 1M input tokens, USD 1.50 / 1M output tokens.
- **Output cap**: 2,048 tokens per call, 16,000 per run. Raising either raises the ceiling on what a
  single run can cost, and the measured median says nothing about the new ceiling.
- **Input size, which is the dominant term.** At these prices input is 6× cheaper per token than
  output and runs are input-heavy — a measured declared case used 10,341 input tokens against 328
  output. The page reduction that decides input size is therefore the single biggest cost lever in
  the system, and a change to the element cap moves cost more than a change of model would.
- **Calls per run**: 12 maximum, 8 exploration and 4 recovery. A typical declared run used **2**
  exploration calls; a recovery adds one call at roughly the same size, so a recovering run costs
  about 1.5× a clean one rather than several times it.
- **Re-asks count twice.** A reply truncated by our own output cap is re-asked, and both calls appear
  on the bill and against the budget. The failure that produces (`output_truncated`) is classified as
  ours rather than the provider's, for the same reason.

The forecast constant the harness prices rounds with is `EVAL_USD_PER_RUN = $0.0042`, taken as the
most expensive dev case at an earlier commit. `r1`'s most expensive case came in at **$0.0048** — the
tail passed the constant, and the 1.5× safety factor absorbed it. That is what a safety factor is
for, and it is why the constant is documented as *last round's maximum* rather than as a parameter.

### 3.3 The honest framing

At USD 0.0019 a run, **cost is not this product's constraint and we should not pretend it was
engineered as though it were.** The interesting cost question is the opposite one: what would have to
be true for this to get expensive. That is the scalability section.

We over-invested here. Roughly five of the spec's amendments concern spend ceilings,
ledgers and credential topology, protecting an outlay whose size is in
[`docs/spend-ledger.md`](spend-ledger.md) and nowhere else — including not in this sentence, which
is the shape the last three stale figures took. That is recorded in §6
as a process finding rather than hidden.

---

## 4. Scalability

Not a growth projection — an honest account of what breaks first.

**Memory binds before anything else.** 2,320 MB peak against 4 GB, with a browser context costing
550–800 MB. The next concurrency step needs RAM, and only RAM. Everything else in the system is
already stateless-per-run.

**What scales cleanly.** The evidence store is content-addressed and append-only; the verifier is a
pure function of (stored artifact, frozen postcondition) and could run anywhere; runs share nothing.
Horizontal scaling is a matter of more browser capacity behind the same queue.

**What does not.**

- **The volume.** Artifacts are the growth term: a real-page DOM runs ~50 KB, an accessibility
  snapshot adds 22–32% of that, and a run stores one of each per capture — call it 0.2–0.5 MB per
  model-driven run. `r1`'s dev split produced 5.95 MiB of carried evidence for 15 cases. Retention is
  14 days and expiry is recorded as a dated state rather than a dangling reference, so the disk is
  bounded — but it is bounded by a policy, not by the architecture, and a heavier workload needs the
  policy revisited rather than more disk.
- **The provider's rate limit binds before our browser does.** 15 requests/minute, configured with a
  margin of 2. At a 12 s median and 2 concurrent runs the system offers ~10 model-driven runs/minute,
  each making 2–3 calls — so the account limit is reached at roughly **five concurrent runs**, which
  is below where memory would stop us. Raising concurrency without raising the provider limit buys
  nothing.
- **Per-site politeness caps throughput per site independently of our capacity.** A crawl delay or a
  documented request ceiling on a target site is binding no matter how much of our own capacity is
  idle, and it is not a limit we would want to engineer around.
- **The one non-linear degradation we measured is memory across concurrent browsers**, and it is why
  concurrency is 2. A third browser context is not a third of the cost of three — the peak, not the
  mean, is what has to fit.

**What would change the design at 100× volume.** The deterministic path scales and the model-driven
path does not. A declared record executes a frozen plan at 0.16 s and USD 0, and 100× of that is a
capacity problem with a known shape: more browser memory behind the same queue, a stateless verifier
that can run anywhere, and an append-only content-addressed store. 100× of the model-driven path is a
different product — it hits the provider's rate limit first, then its own token bill, and the honest
answer is that we would spend the volume on **declaring more records** rather than on more inference.
The declared-record architecture is exactly the thing that makes volume affordable. The caveat is the
one the whole submission rests on: it only covers surfaces somebody has declared and evaluated, and
the experimental tier — which is where a grader's unseen task lands — is the part that does not get
cheaper with scale.

---

## 5. How correctness is verified

This is the section the product is for.

### 5.1 The chain

A claim is `verified` only if a deterministic re-resolution inside the **complete stored artifact**
locates the claimed value, bound to the label the task named, against a postcondition hashed before
the browser opened. The model's assertion is an input to that check and never a substitute for it.

Three properties follow, and each is checkable by a reader:

1. **Reproducible by a third party.** Artifacts are content-addressed and exposed at
   `/api/artifacts/{id}`. Anyone can re-run the verification against the same bytes.
2. **Independent of page drift.** The check runs on stored bytes, so a page changing after the run
   cannot turn a failed check into a passing one.
3. **Not satisfiable by coincidence.** Values bind to labels structurally. A substring that appears
   somewhere on the page is not an answer.

### 5.2 The gates, stated with their scope

| Gate | Result |
|---|---|
| Verified-but-wrong claims = 0 | **Holds on `r1`** — no run returned a value the independent re-check found to differ from the artifact's contents. Read §5.3 before relying on it |
| Required-evidence coverage on `verified` results = 100% | **Holds on `r1`** — every claim marked verified carries the artifact id and SHA-256 it was re-extracted from, and the harness re-fetched and re-hashed each one |

**These hold on our evaluation sets, on first runs. They are not a system-level guarantee**, and any
wording implying otherwise is a defect by our own spec. With n=8 on a held-out split, one failure
moves the rate 12.5 points; the interval is reported, never a bare point estimate.

### 5.3 What the oracles actually check — and where there is none

Written against the code, not against intent. The dev set's case notes described oracles —
*"the harness fetches the table, applies the same sort key, compares"* — that were **never
implemented**. What `eval/harness.py:check_evidence` actually does is: re-fetch each artifact over
the API, re-hash it against the digest recorded at capture, and re-locate each claimed value inside
it. That is a real independent check of *the evidence behind a claim*. It is **not** an independent
derivation of the right answer.

| Record | What independently checks it | What that leaves unchecked |
|---|---|---|
| **OP-4** — sort a table, read the top row | **An independent derivation, since A25.4.** The harness fetches the article itself, finds the table carrying the named column, decides numerically-vs-lexicographically from that column's own values, sorts and compares the top row. It is the one check here that can say a *verified* run is wrong about the world | Whether the article changed between the run and the check. A fetch that cannot be attributed is reported `not_comparable`, never as a failure |
| **OP-5** — expand a collapsed box, read a value | Same: derived values, `independently_checked` **0** | **Everything.** Correctness here rests entirely on the product's own verifier, with no independent ground truth of any kind |
| **OP-6** — category listing, list-level facts | Enumerations are re-derived **member by member** against the stored artifact — the strongest check in the set, and the one absence rests on | Whether the enumeration is complete for a multi-page category (this is L-3, and it abstains rather than guessing) |
| **OP-7** — labelled field on a product page | The value is a scalar and is re-located in the artifact through the label anchor | Whether the label anchor is the one a human would pick. And the record is fixed to one product (§6) |
| Refusals (robots, policy) | The matched rule is quoted and re-checkable against the live `robots.txt` | Nothing material |

**The consequence, and what changed.** An instrument that cannot register the event it is looking for
does not produce a zero; it produces no information, and reporting that as a zero would be the exact
defect this system exists to prevent, committed by us about ourselves. On `r1` that was the state of
both OP-4 and OP-5.

OP-4 now has a real derivation, and the numeric-versus-lexicographic distinction is why it was worth
building rather than only disclosing: the same column sorted the other way is a different top row and
both orderings look completely reasonable on the page. **OP-5 still has none** — expanding a
collapsed box is state that exists only after an interaction, so a plain fetch would disagree with a
correct run, and its correctness rests on the product's own verifier. Every other case's `oracle`
field in `eval/dev-set.md` now names which of the three kinds of check it gets, instead of all
fifteen claiming a derivation that no code performed.

Disclosing that costs a paragraph. Being found to have declared an oracle that never ran costs the
argument.

### 5.3.1 What the difference between r1 and r2 does and does not measure

The dev split has been scored twice against the deployment. The headline moved from **6 of 11** to
**9 of 11**, and the honest reading of that is narrower than the number looks.

**r2 is not a single-variable change, and the plan that it would be was overtaken.** It was supposed
to carry the scorer's corpus fix and nothing else, so that `r1 → r2` would isolate a measurement
defect from a product improvement. It does not: the build it ran on also carries OP-7's parameter
generalisation, the n-claim postcondition, and locator memory. The engineering session continued down
the amendment's ordering while waiting for an operator action that only the product owner could take,
and the round boundary that was to do the isolating was spent before those changes landed. That is a
sequencing mistake and it is recorded as one.

**What isolates the measurement defect instead is stronger than the round boundary would have been.**
The four cases that r1 demoted were re-checked against **r1's own stored artifacts** — the actual
bytes, pulled from the scored volume — under the corrected corpus. All four resolve, and none of them
resolves in any of the places the corpus deliberately excludes (a script literal, a class name, an
`id`, a `data-` attribute, a URL, a comment). The measurement defect accounts for exactly four of the
five cases the r1 headline was missing, on evidence that predates the fix and cannot have been
influenced by it.

So: **r1 → r2 is a measurement defect removed *and* three product changes, in one step**, and the
artifact replay is what separates them. Conceding the confounding and pointing at independent
evidence is worth more here than re-running a round and asserting it was clean — the re-run would be
a fourth build, and this document would have to explain why *that* one was single-variable.

### 5.3.2 The held-out split, and the thing it measured that we had not

`r4` scored the eight held-out cases once, on the frozen build, against a file whose SHA-256 was
checked before the first case. **1 of 8.** The dev split on the same build was 10 of 11.

A gap that size between a set we wrote and a set we did not is the most informative number in this
document. The histogram is where you start — three `robots_disallowed`, two `policy_refused`, one
`budget_exhausted`, one `postcondition_unmet`, one success; **five of the eight never browsed** —
and it is *not* where you finish, which this section originally got wrong and §5.4's defect 10
records in full. Opened case by case, those five are two different things: **three were a
`robots.txt` fetch that timed out** on a site that publishes none, and **two were refused for naming
no page or site to start from**. Only the second pair is a property of the system.

That leaves five cases carrying any signal about capability: two refused at admission, two that
browsed and failed (`budget_exhausted`, `postcondition_unmet`), one verified. An even split on
**n=5**, which is not enough to name a bottleneck — and an earlier version of this section named
one.

With that said, the two sets were still not measuring the same thing:

- The dev and experimental splits measure **how well the system answers a task it accepts.** On that
  question the answer is good, and `r3` is the evidence.
- The held-out split measures **how many reasonable tasks it accepts at all.** On that question the
  answer is poor — two of eight were refused for naming no page or site to start from, and three of
  four declared-tier cases did not reach the tier they were declared at. Nothing we had built could
  have told us, because every case we wrote ourselves was written by someone who already knew what
  the router takes. (This is stated in the README as well, beside the support matrix and the score,
  because it is the conclusion and not the appendix.)

**The three `robots_disallowed` are not what they looked like, and the correction is worth more than
the original reading.** They were first written up here — and in the README — as our own cases
hitting our own policy, evidence that our sense of an ordinary task was wider than the rules we
chose. That was wrong. It was caught within the hour, by opening the evidence we had just rescued
and published, which is the only reason it is a correction and not a claim in a submitted document.

What the three actually are: **one transient network failure, on one host.** All three carry the
identical `robots` record — `source: "unfetchable"`, `rule: "robots.txt could not be fetched:
URLError: <urlopen error timed out>"`, no directive and no pattern, because nothing matched. An
unfetchable `robots.txt` is refused by design (it is a row in
`docs/m4-fail-closed-inventory.md`: 404 means unrestricted, unreachable means refuse), and that is
the correct action — we will not browse a site whose policy we could not read.

The site in question, `books.toscrape.com`, publishes **no `robots.txt` at all**. It returns 404,
which the matcher reads as unrestricted. It did so for seven cases in `r3`, twenty minutes before
this round, and it does so now in 0.6 seconds. Three held-out cases on a **promised** site were lost
to a fetch that timed out inside a 78-second window.

Three things follow, and the first is the one that matters:

1. **`r4` measured availability as much as capability, and 1 of 8 is therefore a floor.** The number
   stands — the first run is the reported score (S-10.6), and a round is not re-taken because it
   went badly. But a reader who takes it as a capability estimate is reading it as more than it is,
   and this paragraph exists so that the qualifier travels with the figure, which is the rule this
   whole document is written under.
2. **The failure class conflates two different events**, and that is defect 10 below. `the site
   forbade this` and `we could not ask the site` both arrive as `robots_disallowed`. The refusal is
   right in both cases; the label is right in only one, and a reader counting policy refusals across
   a round cannot separate them without opening each trace — as we did not, at first.
3. **There is no retry**, and one is not obviously correct: retrying a policy fetch is a decision
   about how hard to try to be allowed, which is exactly the kind of decision that should not be
   made quietly. It is named here as a gap rather than patched in after a bad round.

Three tier disagreements make the same point structurally: two cases declared `T-DECLARED` were
routed experimental by the running system. A promise stated per `site × operation` is only worth the
breadth of phrasings that actually reach it, and OP-7's fixed-product defect — found and fixed
before the freeze — was evidently one instance of a wider pattern rather than the pattern itself.

**What we would do with another day** is not model work. It is a corpus of phrasings per promised
record, written by someone who has not read the router, with the admission gate scored against it —
the same two-sided-corpus discipline `docs/m4-fail-closed-inventory.md` already applies to the
out-of-scope classifier, applied to the tier assignment instead. The refusals themselves are
correct; each quotes the rule that matched. It is the reachable surface behind them that is
narrower than the support matrix implies.

**One process note, against ourselves.** No evidence bundles were exported for `r4`. Held-out
results withhold per-case detail at the point the file is written, and the bundle exporter reads
that same withheld structure — so the round with seven non-successes carried zero bundles, on
exactly the split whose failures are most worth inspecting. The runs and artifacts are in the
scored service's store; nothing carried them out. It was found by reading the manifest after the
round rather than by anything in the system, which is the same shape as every other entry in §5.4.

### 5.4 Verifying the verifier

A system whose central claim is "our checks are real" has to expect the checks themselves to be
wrong. **Ten** defects of that exact shape were found, seven of them fixed, all the same species —
**a check that reported on a coincidence**, a check that could not fire at all, or a label too
coarse to carry the conclusion drawn from it. The first five were found during development:

| | The defect |
|---|---|
| 1 | A constraint recorded as *satisfied* when it had never been evaluated |
| 2 | A precondition satisfied by another process's side effect rather than by the thing under test |
| 3 | A vacuous branch reporting a check as passed when there was nothing to check |
| 4 | A test encoding a defect as a requirement, so fixing the defect broke the test |
| 5 | Declared evaluation oracles that were never implemented — **the first one whose direction was optimistic** |

The first four made correct behaviour look broken; the fifth made unproven behaviour look proven.
That asymmetry is why the fifth survived longest, and it is the reason an independent review that
ran the deployed system found things that reading diffs did not.

Three more of the same species were found after that list was written, and they are here rather than
in an appendix because the pattern is the finding rather than the count:

| | The defect |
|---|---|
| 6 | The accessibility snapshot took its own trace entry, and every trace entry charges the step budget — so capture-heavy runs silently had half the browsing headroom they were designed with. Found by *executing the published limitations list*, not by a test |
| 7 | `page.url` was sampled at one instant to record where a navigation ended up. On identical inputs — a frozen target of `/wiki/Apple_Inc` and a page that ends up at `/wiki/Apple_Inc.` — one scored round recorded the later URL and the next recorded the earlier one, so a correct run failed `artifact_source_matches_plan` against **its own artifact**. Fixed in two attempts; the first did not hold, and that is the part worth reading |

| 8 | `internal_error` is the class for *our* defects, and it is the one rate the spec treats as a finding in itself. In `r3`, EXP-05 ended there because the planner proposed an element reference that was not in the view it had been sent — the run refused, correctly and fail-closed, and then filed the refusal under our own name. A model inventing a ref is not our code failing. **Found and not fixed**: see below |

| 9 | The dry run's job is *everything that can fail before money is spent*, and it skipped the two checks a held-out round needs most: that the case file is mounted where the operator said, and that its hash matches the committed one. It empties the split list right after printing the forecast, so both run only on the real start. The runbook told the operator to look for the hash line in the dry run — a line that path cannot print. **Found and not fixed**, for the same reason as 8 |

| 10 | `robots_disallowed` is returned both when a rule forbade the path and when `robots.txt` could not be fetched at all. Both refusals are correct; only one of the two labels is. In `r4` three held-out cases carried it for a **timed-out fetch** on a site that publishes no `robots.txt`, and the round was first written up as a finding about our policy's coverage — by us, from the histogram, before anyone opened a trace. **Found and not fixed** |

Number 10 is the one to read if you only read one, and the chain of events is the point rather than
the defect.

The product owner read the failure-class histogram, saw three `robots_disallowed`, and instructed
that it be written up as a finding about our policy's coverage — a good reading of the only evidence
in front of them, and wrong. The engineering session wrote it into two documents. It survived
because nothing in the round's *summary* could contradict it: the histogram is exactly as precise as
the failure class, and the failure class was not precise enough.

What broke it was clicking a link. The evidence for that round had been rescued off the volume by
hand an hour earlier — the round exported none — and published; the last step before submission was
to confirm a grader could open a failing case. Opening one showed `source: "unfetchable"` where a
matched rule should have been, and the claim collapsed in a minute.

So the causal chain runs: **an aggregate too coarse to be checked → a confident conclusion drawn
from it by the person who set the requirements → written into the submission → caught by evidence
that had existed for one hour, because somebody opened it.** Every other entry in this table is a
check reporting a coincidence. This one is *us*, at the last possible moment, doing precisely what
this system is built to stop a model doing: producing a plausible answer that nothing in the summary
could falsify. That is the
argument for the whole design — the trace was there and it disagreed with the summary — and it is
also the sharpest demonstration in this project that a well-organised number is not the same as a
true one.

Numbers 8, 9 and 10 arrived after the build was frozen, which is the only reason they are still
open, and how that was handled is part of the finding. Correcting any of them would have meant a code change between the
round that measured the system and the round that scores the held-out split — so the choice was
between tidier code and two rounds that describe the same build. The code lost. It is
written here, in the table with the other seven, rather than repaired quietly afterwards and
presented as though the rounds had always agreed. Number 8 is the same species as A-14b: a loud, correct refusal
filed under the wrong party. Number 9 is the species this whole section is named for — an
instruction to look for evidence that the code cannot produce — and it cost a real operator a real
scare mid-round before anyone read the code path.

Number 7 is the one worth reading twice, and it took two goes.

**The first fix was to record the response's URL** instead of `page.url`, on the reasoning that a
response's URL is the end of the redirect chain and cannot be timing-dependent. That reasoning was
sound and the premise was false. Measured afterwards with a browser rather than assumed:
`https://en.wikipedia.org/wiki/Apple_Inc` answers **200, with no redirect at all**, and the address
bar changes to `/wiki/Apple_Inc.` about **two seconds later**, from MediaWiki's own script. There was
never an HTTP hop to record. So the first fix would have pinned the gate to `/wiki/Apple_Inc` — a URL
that never matches the artifact — and turned an intermittent failure into a reliable one.

**What made the first fix wrong is more general than that page.** The gate compared *one* frozen plan
target against *one* recorded endpoint. Whenever anything moves the page — a 301, a canonical
rewrite — those two are not equal, so a single comparison has only two available behaviours: pass
every move or fail every move. Choosing which URL to record chooses between them. That is not a gate
being repaired; it is a coincidence being swapped for a steadier coincidence.

**Amendment 26 splits it into two assertions over three recorded values** — the plan's target, the
full redirect chain with each hop's status, and where the navigation ended:

1. **`artifact_source_is_a_url_the_run_reached`** — the bytes a claim is verified against came from
   a page this run's trace can account for having been on. *Where did the evidence come from.*
2. **`landing_explained_from_the_plan_target`** — that page is reached from the plan's target by a
   recorded route: it is the target itself, or the end of a redirect chain that began there, or the
   canonical URL the document served at the target declared for itself. *Is the landing accounted
   for.*

The third route is what the Wikipedia case needs and what no endpoint comparison could supply: when
the move happens in script after the response, the document's own `rel=canonical` is the only
recorded fact that does not depend on when it was read. It is a claim by an untrusted page, so it
counts only from the page the *task* named and only same-origin — otherwise a third-party page could
explain away evidence that came from somewhere else.

**And that route is the weakest of the three, which is worth saying out loud rather than leaving in
the code.** A redirect chain is an *observation*: our own browser was sent from one URL to another
and recorded each hop with the status that caused it. A canonical link is a *page's statement about
itself*. DEV-04 — the case this whole section is about — passes on the second kind. What holds it up
is not that we watched Wikipedia move us, but that Wikipedia said where it lives and the same-origin
rule bounds how far that statement can reach: a page may rename itself only within its own origin,
so the worst a hostile site can do with it is account for evidence it served us anyway. That is a
real bound and it is not the same as having seen it happen. A document that spends this many pages
asking *"what would have to be true for this check to be reporting a coincidence"* does not get to
skip the question when the answer is inconvenient — so: this one rests on a self-description, and if
that were unacceptable, the honest alternative would be to fail DEV-04 rather than to widen the rule
until it passed.

Both assertions can fail alone, and the fixture carries a case for each, because an assertion that
cannot fail is the defect in this table one row up. The one that matters is `/detour`: it 301s to
**exactly the same page** as `/moved`. A run sent there arrives at the right final URL by a door the
plan never opened — final-URL comparison passes it, and reaching the right answer by an unaccounted
route is what this system scores as a failure.

The wider point is the same one as the rest of this section: a hard gate whose outcome depends on
when a variable was read is not a gate, so every earlier pass of it was worth slightly less than it
looked — and a fix that merely stops it wobbling restores the appearance rather than the gate. It
cost one case in round r2, and it was found because that case had passed in r1 on inputs that had not
changed.

### 5.5 The one operational failure, and what the system did about it

Everything above is a defect in code. This is a mistake by a person, on the live system, and it is
recorded here because the response to it is the best evidence in this document that the design works.

**What happened.** The product owner started scored round `r2` and said so. Four minutes later the
engineering session pushed a commit. On this host a push to `master` **is** a deployment (Amendment
20), so the scored container was replaced while it was scoring a paid round. Nothing about this was
arranged, simulated, or triggered on purpose; the engineering session had been told the round was
starting and pushed anyway.

**What the system did.**

- The **dev split had already crossed its boundary** and was written under its clean name,
  `dev-deploy-aa1ee6c5d5eb-r2.json`, with the commit it ran on inside it. It is a valid measurement
  and is used as one.
- The **experimental split was interrupted mid-way**. It left
  `eval-results/.rounds/r2-experimental.inflight.json`, and the next start of the workload **refuses
  to run that split again** rather than silently re-spending the money — the operator has to read the
  log and decide, which is the entire point of the marker.
- Nothing was written under a name that would later read as a completed round, and no partial result
  was aggregated into anything.

**Why it is in the main text.** A long line of amendments argues for this behaviour: that a push is a
deployment, that a round is locked to the build it started on, that an interrupted paid split must
fail closed rather than re-run itself. This is the first time any of it was triggered in the wild,
by an actual mistake rather than by a test. A clean `r2` would have added one row of numbers; this
file demonstrates that the mechanism fires. The round it cost is priced in the ledger, and it was a
good price.

The correction was procedural, not technical: the remaining rounds are run on a frozen commit with
no pushes in between, and the test split is run **on its own** rather than sharing a round with a
split that might be interrupted — a held-out first run cannot be taken twice.

**Mutation results, as shipped.** The fixture declares a mutation catalogue and **two** mutations are
wired: `mu2-text` (control and label text changed under the locator) and `mu6-overlay` (a banner that
covers the pager and swallows the click). Both are reachable from the frontend with a `seed`
directive, and both are demonstrated on our own fixture — which is why they are published as
*mechanism evidence* and appear in no success rate: a repair rate measured on a site we wrote is us
marking our own exam.

MU-4/5/7/9 and the full sweep were **cut** (Amendment 25): two working mutations plus one healing
demonstration is evidence, nine is a research programme, and the marginal mutation shows nothing the
first two have not.

**Write-back, and the healing demonstration.** Locator memory is built at the reduced scope above,
so a repair now survives the run that made it. The demonstration A14.6 asks for runs against **the
real books.toscrape Nonfiction listing, archived byte for byte**, and against a copy of that page
with the pager rewritten the way a redesign rewrites things — new class, new wrapper, a `data-` hook
where there was none, accessible name untouched. `li.next a` is our spelling of the control and does
not survive it; *the link whose name is "next"* is the page's own spelling and does. The asymmetry is
the claim, and it is checked in `tests/test_healing_demonstration.py` with a browser driving both
archived files.

What is still weaker than it reads: the demonstration is one page and one mutation shape, and memory
engages where a locator has stopped resolving rather than as a first resort. More than that: **no run in any committed result file has yet been recorded producing a genuine
cross-family strategy transition** (A-11). The mechanism is built, it is exercised by the suite, and
the field evidence for it is one demonstration rather than a rate. A mechanism we are confident in
and cannot point at a production instance of is exactly the kind of claim this report is supposed to
make uncomfortable.

### 5.6 Silent failure — the metric we actually care about

Loud failures are cheap: the run says what it could not do and a reader believes it. A silent failure
is a plausible wrong answer, and it is the only outcome that damages the user.

**Definition used**: a run that returns a plausible answer, labelled as a success, which is not the
answer to the question asked — including a correct-looking value read off the wrong page, an absence
concluded without proof, and a partial answer presented as a whole one.

**Count across every committed split: zero runs were released as a silent failure.** That number
means very little on its own, so here is what stands behind it and where it is weakest.

*How one would be detected if it happened.* Four independent mechanisms, each of which has actually
fired on real runs during development:

1. **Artifact origin against the task's own words.** A run that answered about our fixture while the
   task named Wikipedia was caught by comparing the artifact's origin to the site the task named,
   read by the verifier and not by the router.
2. **Frozen-parameter comparison.** A task asking to sort by *CIK ascending* was handed the canned
   *GICS Sector descending* plan, executed it perfectly and returned `succeeded_verified`. Every
   structural check passed, because every structural check compares the run to the plan and nobody
   compared the plan to the task. Four dev cases were being answered that way. The plan's frozen
   inputs are now checked against the task's own words.
3. **Absence requires positive proof.** `no_result_verified` needs a located empty-state element or a
   coverage anchor covering the whole result set. Without one the run abstains — this is L-3, and it
   costs us measured points.
4. **`app/suspicion.py` audits quiet outcomes against the reduction log.** An abstention caused by
   *our own* page reduction dropping the element looks exactly like an honest abstention, so every
   quiet outcome is checked against what the reducer removed and badged when the two line up.

*Where the zero is weakest, stated plainly.* §5.3 is the limit: on OP-4 and OP-5 no independent
oracle derives the right answer, so a silent failure on those two records would have to be caught by
the product's own verifier — which is the thing being checked. And mechanism 4 only covers what we
thought to look for; an abstention caused by something we have no counter for is indistinguishable
from a correct one. **A zero produced by an instrument that cannot register the event is not a
result**, and on our two strongest records the instrument is partly blind.

*What was found by running the deployed system as an adversary rather than reading the code:* a live
`succeeded_verified` on a request for *"UPC and availability"* that froze one unnamed claim, verified
the UPC and silently dropped availability. That is a silent failure by the definition above, found
after the splits were scored and not by them. It is fixed by requiring a task with *n* asked-for
parts to produce *n* claims or return `partial` — and it is the clearest evidence in this document
that a split you wrote yourself does not measure the surface a stranger's task lands on.

---

## 6. What we traded away

Stated as decisions with reasons, because a submission that lists only what it built is not being
honest about a two-day calendar.

| Cut | Why |
|---|---|
| **Task 2 entirely** | The assignment requires one task. `docs/task2-seam.md` is frozen as a designed-not-built contract. A fully specified interface for a product that will not exist is a straight subtraction from the one that will |
| **The validation split** | Its purpose was to keep the engineering session honest during development. Development ended. Test is run once against the deployment; validation is reported as unrun, with this reason |
| **The mutation sweep (9 → 2 mutations)** | Two working mutations plus one healing demonstration is evidence. Nine is a research programme |
| **Most of the safety suite** | **Not built, and declared as not built.** What exists is the egress guard, robots enforcement and the refusal taxonomy, all of which are load-bearing and tested. What does not exist is a safety split (`eval/safety-set.md`) or an injection detector — so `injection_detected` is a declared status **no code path currently reaches**, and `/coverage` says exactly that. The build-state flags are derived from whether the module and file exist, so the support page cannot advertise a suite that is not there |
| **Further spend-ceiling and ledger work** | [`docs/spend-ledger.md`](spend-ledger.md) has what it protected. It was done, and it was over-done |
| **Locator memory's full scope** | **Built, at the reduced scope, on the last day.** A table on the volume keyed by `(origin, operation, role)`, written back **only** from `succeeded_verified` runs, 14-day confirmation window, quarantine after three consecutive failures, counters on `/healthz`, and the run page badging each interaction *from memory* / *healed* / *freshly derived*. Not built: cross-site generalisation, ranking, a learned selector model, or any use of memory as a first resort on the model-driven path — it engages where a locator has stopped resolving, which is the case it exists for. The frontend derives the claim from the code, so if this is ever removed the page stops selling it |

**Process finding, stated against ourselves.** Six of the last eight spec amendments concerned the
measuring apparatus — ledgers, budget ceilings, evaluation provenance, the spec's own change
discipline — rather than what the product can do. The instinct that produced them is the same one
that found all seven broken checks in §5.4, and it is genuinely the most valuable thing in this
repository. It also became the failure mode: while it was auditing the instruments, nobody audited
the promises, which is how a false limitation and a support matrix that overstated a record both
survived to a live deployment. The correction was to run the deployed system as an adversary instead
of reading the code.

---

<!--
Every FILL slot has been filled from a committed measurement file, or marked "not measured" with
the reason. No slot carries an estimate presented as a measurement. If a figure here stops being
true of the built system, the figure is the defect — re-measure, or say what changed.
-->

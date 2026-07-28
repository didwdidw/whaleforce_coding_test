# Task 1 — Generalized Browser Automation Agent

Give it a task in plain English. It runs the task in a real browser against public, read-only pages,
and returns either **a verified answer with the evidence used to verify it**, or **an honest
non-success status that says what it could not do**.

It is built for one user: someone who would rather have no number than a wrong one.

**Live system:** <https://wf-agent.zeabur.app>
**Frontend surfaces:** `/` submit + recent runs · `/runs/{id}` full trace · `/support` support matrix
and known limitations · `/coverage` evidence coverage · `/healthz` operational state

---

## 1. The one idea

Most browser agents fail the same way: the model looks at a page, says *"the answer is 42"*, and the
system reports 42. If the model was wrong, nothing in the pipeline can tell. That is a **silent
failure**, and it is the failure mode this product is designed against — the assignment penalises it
more heavily than a loud one, and so do we.

So the model is never the source of truth about what a page said.

1. **Before browsing**, the task is compiled into a **postcondition** — the claims that must hold for
   this task to be answered, plus the UI actions that must actually have happened. It is hashed and
   frozen. Nothing downstream can edit it.
2. **During browsing**, every page state that matters is stored as an artifact (full DOM + text +
   screenshot), content-addressed by SHA-256.
3. **After browsing**, the model proposes an answer — and that proposal is treated as a *hypothesis*.
   A deterministic verifier re-opens the stored artifact and tries to locate the claimed value again,
   bound to the label the task asked for. If the value cannot be re-resolved inside the stored bytes,
   the run does not succeed, however confident the model was.

The load-bearing sentence is: **the model proposes, deterministic code disposes, and the evidence it
disposes over is stored bytes rather than a live page.** A live page can change between the answer
and the check; stored bytes cannot.

Two consequences worth stating plainly, because they cost us headline numbers:

- **Absence is never inferred.** "I looked and didn't find it" is not proof that nothing matches.
  `no_result_verified` requires either a located empty-state element or a coverage anchor proving the
  whole result set was read. Otherwise the run abstains. (This is why L-3 exists.)
- **Reaching the right answer the wrong way is a failure.** If a case declares that a form must be
  submitted and the run guesses the result URL instead, it is scored **fail** even when the value is
  correct. An agent that passes by shortcut has not demonstrated the capability being claimed.

---

## 2. Running it

### Use the deployed system

Open <https://wf-agent.zeabur.app>, type a task, watch it run. The homepage carries pre-executed runs — including
failures — that are inspectable immediately, so nothing depends on a cold container starting.

The API, if you prefer:

```bash
curl -X POST https://wf-agent.zeabur.app/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"task": "On books.toscrape.com, open A Light in the Attic and tell me its UPC."}'

curl https://wf-agent.zeabur.app/api/runs/{run_id}          # status + result + evidence bundle
curl https://wf-agent.zeabur.app/api/runs/{run_id}/events   # SSE progress stream
```

### Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium

export APP_ENV=development             # relaxes the egress guard for a loopback fixture only
export DATA_DIR=./.data/task1          # runs database + artifact store; created if absent
export FIXTURE_BASE_URL=http://127.0.0.1:8801
export PROVIDER_KEY_DIR=./api_keys     # a *directory*; the key is read from a file in it
export PROVIDER_FREE_KEY_NAME=gemini_free_tier   # ./api_keys/gemini_free_tier
export CREDENTIAL_POLICY=development   # free tier, falling back to paid if present
export PORT=8080

# The fixture is a separate process on its own port, because the app treats it as a remote
# site like any other. Start it first.
APP_ROLE=fixture PORT=8801 ./entrypoint.sh &
./entrypoint.sh                        # app on :8080
```

**No LLM credential is required to see the system work.** The fixture demonstrations and the pinned
homepage runs take the deterministic path, which makes no model call at all — so a reviewer with no
key still gets a browser really driving a real page, with the evidence and the verifier's verdict.
What needs a key is the model-driven path, which is everything on a site we did not write.

### Tests and evaluation

```bash
pytest                                    # 600 tests, ~17 s (a real browser runs
                                          # in tests/test_m2_integration.py)
python -m eval.harness --split dev        # the dev split, committed in eval/dev-set.md
python -m eval.harness --split experimental
```

---

## 3. What it promises, and what it does not

Reliability is promised per **`site × operation` record**, never per website. Knowing how to sort a
table on Wikipedia says nothing about whether we can expand a navbox on Wikipedia; those are separate
records with separate evidence. Every task is assigned a tier **before execution**, and the tier is
visible on the form, in the result, and in the API response.

| Tier | What it means | Counted in the headline rate |
|---|---|---|
| **T-DECLARED** | Matches a promised record below | **Yes** |
| **T-EXPERIMENTAL** | Any other public, policy-clean, read-only site. Best-effort; abstention is a correct outcome | **No** — reported separately |
| **T-REFUSED** | Violates the policy in §5. Refused before any browsing | n/a |

### Support matrix

**The promised set is four records, not seven.** OP-1…OP-3 were on our own fixture, and a record
measured on a site we wrote is us setting our own exam — so they were **withdrawn from the promise**
and kept as *mechanism evidence* (GS-1…GS-3 at `/support`), which appears in no success rate. The
promise is what is left, on sites we do not control.

| ID | Site | Operation | Why it is hard | Status | From |
|---|---|---|---|---|---|
| OP-4 | en.wikipedia.org | Sort a sortable wikitable by a named column, read a cell from the new top row | Client-side sort: the DOM order changes, the URL does not, so the answer cannot be obtained by fetching a URL | **2 of 3 dev cases as expected.** DEV-01 carries an independently derived top row that **agreed across all 8 cells**; DEV-03's column is not one the oracle can find on that page, so it is reported as un-derived rather than as checked. The third (DEV-02) names the article by description rather than by title and correctly stops before browsing — see L-1 | `r3` |
| OP-5 | en.wikipedia.org | Expand a collapsed section/navbox and read a value not visible beforehand | The value is not in the DOM-visible state until a real interaction happens | **2 of 2.** DEV-04 spent `r2` failing this record on the artifact-source gate rather than on the operation; Amendment 26 rebuilt that gate and the case passes again — on the weakest of the gate's three routes, which §5.4 of the analysis report says so about. No independent oracle: correctness here rests on our own verifier (A25.4) | `r3` |
| OP-6 | books.toscrape.com | Navigate a category, page through it, extract list-level facts | Multi-page state, and the honest answer often requires proving coverage | **2 of 3.** The third exhausts the step budget on a long category and returns no answer — L-2. It has done this in all three rounds | `r3` |
| OP-7 | books.toscrape.com | Open a product detail page and extract a **labelled** field (UPC, Availability, Price excl. tax) | The answer is a label→value binding, not a string that happens to appear | **2 of 2**, and this is the first round scoring it *after* the product became a parameter: it takes the title from the task and reaches it by paging the listing, bounded to 6 pages. A title beyond that ends `unsupported` naming the bound rather than reporting the wrong book | `r3` |

Four of the six *evidence findings* in `r1` were the harness disagreeing with itself, not the
product: it re-checked values against rendered text only, and `books.toscrape` carries long titles in
the `title` attribute, which the product read — the better behaviour. In `r2` those four are gone and
two findings remain, both tier disagreements. `r1` stays committed as the record.

**These records are the promise. Everything else is best-effort and is labelled as such in the UI.**
A grader submitting a task we have never seen gets a T-EXPERIMENTAL run that browses honestly and
abstains when it cannot prove its answer — not a confident guess.

### The promise has a language

The declared promise is **English tasks only**. Chinese and other languages reach the experimental
path at best. This is a stated limitation, not an oversight — a promise we have not evaluated is not
a promise.

---

## 4. Key design decisions

Every entry here is a decision with a cost we accepted, not a feature list.

**The postcondition is frozen and hashed before the browser opens.**
The alternative — deciding what counts as success after seeing the page — is how an agent talks
itself into an answer. Freezing it means a run can fail because we asked the wrong question, and that
failure is visible instead of absorbed.

**Verification re-resolves inside the stored artifact, not the live page.**
Re-checking a live page invites a different failure: the page changed, the check passed, and the two
facts are unrelated. Stored bytes make the check reproducible by anyone holding the run's artifacts —
including a grader, via `/api/artifacts/{id}`.

**Values bind to labels structurally.**
A string appearing somewhere in the page is not the answer to *"what is the UPC"*. The verifier
requires the value to be reachable from the label the task named, which is what makes OP-7 a real
capability rather than a substring search.

**Tiers exist so the honest answer to "does it work on any site?" is a number.**
Claiming general capability is easy and unfalsifiable. Declaring four records with evidence, on sites
we do not control, and measuring everything else separately as best-effort, is the falsifiable
version of the same claim. The cost is that our headline rate covers a smaller surface than a vaguer
product would advertise — and it got smaller again when we withdrew the three fixture records for
being an exam we set ourselves.

**Retry and recovery are different things and the system never conflates them.**
Re-running the same strategy after a flake is a *retry* and is recorded as one — it is not
self-correction, and counting it as such would be the easiest way to fake this requirement. A
*recovery* is a move to a different strategy family (accessibility tree → text anchoring →
structural → alternate route → alternate representation) triggered by a **named diagnosed cause**
from a closed set. "The step threw an exception" is not a diagnosis and is not accepted as one.
Screenshot-coordinate clicking is a last resort and is refused at the planner boundary: blind
clicking produces the exact failure mode this product exists to prevent.

**Fail-closed budgets.**
Every run has a step and token budget. Exhausting it produces `budget_exhausted` with no answer,
rather than reporting the page we happened to have reached as though it were the last one. L-2 is
this decision showing up as a limitation, and we left it in.

**Every non-success has a `terminal_status` × `failure_class` from two closed sets.**
Seven statuses, eighteen failure classes, extended only by a written amendment. `partial` and
`unverified` are never rendered, aggregated, or described as success anywhere in the product — a
guarantee that only means something because the sets are closed and the rule is mechanical.

**books.toscrape.com was chosen because its automation policy is unambiguous.**
It is a sandbox published for exactly this purpose. **arXiv was dropped** because its robots policy
disallows `/search`, `/find`, `/form` and `/api` and its stated policy forbids indiscriminate
automated downloads — the operations we wanted were the ones it forbids. We are not repackaging that
as a research decision. `robots.txt` matching is a real RFC 9309 implementation with its own CI job,
because a policy check that is subtly wrong is worse than none.

**The public deployment is read-only, re-validates the target IP on every hop, and treats all page
text as untrusted data.** Text on a page can never change the goal, the tier, the policy, the
budgets, or the memory. This is enforced structurally — the memory feeds locator resolution only and
is never injected into the planner as free-form instruction — rather than by asking the model
nicely.

---

## 5. Where AI helped, and where it did not

The whole system was built by AI sessions with a human product owner. Being specific about that is
part of the submission.

**The division of labour.** Two Claude Code sessions with deliberately separated roles: a **product
owner / acceptance session** that owned the spec, wrote the acceptance criteria, adjudicated
disputes and never wrote product code; and an **engineering session** that implemented from the
frozen spec and never decided what "correct" meant. The separation was the point. A single session
that both defines success and reports success will report success — which is the same defect, one
level up, as an agent that both answers and verifies. `docs/task1-spec.md` §16 is the record: every
change to the spec is a numbered amendment appended to frozen text, each with
the defect that caused it.

**What AI was clearly good at.** Writing the deterministic verifier, the RFC 9309 robots matcher, the
evidence store and the taxonomy plumbing — dense, rule-following code with sharp edges. Also at
adversarial reading: several of the amendments exist because one session found a defect in the
other's work that neither the tests nor the spec had asked about.

**What it was bad at, concretely.** Three defects in this repository were produced by AI and found
only by an independent AI review that actually ran the deployed system:

- A published limitation (L-1) whose stated workaround **did not work**, reproducible in thirty
  seconds.
- A promised record (OP-7) hardcoded to a single product, which made the **support matrix above**
  false for every other product — the promise was written correctly and implemented narrowly.
- An evaluation harness declaring independent oracles it **did not implement**, which made our
  strongest correctness claim unfalsifiable.

The pattern is the same in all three: **fluent, structurally correct, confidently stated, and not
checked against reality.** Every one of them is a claim about the system rather than a bug in it,
which is exactly the class of error that reviews aimed at code do not catch. What worked as a
counter was running the deployed system as an adversary rather than reading the diff.

**Where the human was load-bearing.** Deciding what to cut, refusing to accept point fixes where a
requirement class was needed, and the calls that spent money or changed what we promised. Amendment
25 — the subtraction — is the clearest example: the AI sessions would have kept building.

---

## 6. Evaluation

Four splits, all authored by us against public pages. Every result file carries its own
provenance — git SHA, pinned model, credential tier, and the SHA-256 of the split file it scored —
because a score without them describes a system nobody can identify. Full numbers, per-case tables
and the evidence bundles are in `eval/results/` and `docs/analysis-report.md`.

**The headline round is `r3`**, scored against the frozen submission build. Three rounds were run;
all three are committed, because a number that only survives because the rounds that disagreed with
it were deleted is not a measurement.

| | `r1` | `r2` | **`r3`** |
|---|---|---|---|
| What it is | first round against the deployment | dev re-scored on the corrected harness | **the frozen build, both splits** |
| Commit | `e1d13cae4926` | `aa1ee6c5d5eb` | **`e82cacb9e809`** |
| Model | `gemini-3.1-flash-lite` | `gemini-3.1-flash-lite` | `gemini-3.1-flash-lite` |
| Credential tier | paid | paid | paid |
| Dev split file | `8f584218…` | `9c1a0dee…` | `9c1a0dee…` |
| Experimental split file | `790d9440…` | *interrupted — analysis report §5.5* | `790d9440…` |
| Ran (UTC) | 2026-07-28 14:26–14:31 | 2026-07-28 17:05–17:07 | 2026-07-28 18:58–19:04 |
| Dev headline | 6 of 11 | 9 of 11 | **10 of 11** |

**Dev split — 15 cases, 14 declared.** Thirteen of the fourteen ended in a status the case declared
acceptable. The one that did not is the product refusing rather than guessing: DEV-08 exhausts its
step budget paging a long category and returns no answer (L-2). It has done so in every round.

The **headline pass rate is 10 of 11**, lower than the status count because a case passes only when
the status is as expected *and* the harness can re-locate every verified value in the stored
artifact. Two evidence findings remain across the whole split, and both are tier disagreements
(DEV-02, DEV-13) rather than anything about a value.

**What moved between the rounds, and why it is not one story.** `r1` at 6 of 11 was mostly *our
scorer* being wrong: four of its five misses were the harness searching rendered text only, while
`books.toscrape` carries long titles in a `title` attribute the product correctly read. `r2` at 9 of
11 fixed that, but was not a single-variable change — its build also carried OP-7's parameter
generalisation, the n-claim postcondition and locator memory, and the analysis report §5.3.1 says so
rather than claiming the round boundary isolated anything. The case that separates measurement from
product is the artifact replay: r1's own stored bytes, re-checked under the corrected corpus,
account for exactly four of r1's five misses.

`r3`'s single gain over `r2` is **DEV-04**, and it is worth naming because it is the opposite
direction: that case was *correct* in `r2` and was failed by our own artifact-source gate, which
compared a frozen target URL against a page Wikipedia had moved. Amendment 26 rebuilt the gate as two
assertions over a recorded redirect chain, and the case passes on the weakest of its three routes —
the page's own `rel=canonical`, bounded to same-origin. The analysis report §5.4 says that plainly
instead of letting the number stand unqualified.

**One check that could have caught a wrong answer, did run, and agreed.** DEV-01's top row was
derived independently — the harness fetched the article, decided numeric-versus-lexicographic from
the column's own values, sorted, and compared. All 8 cells agreed. DEV-03's column is not one the
oracle can locate on that page, and it is reported as *not derived* rather than as checked.

**Experimental split — 10 cases, all on sites we had never touched.** Attempted 10/10; **verified
3/10** (95% Wilson interval **0.11–0.60**); abstained after looking 3/10; failed or blocked 4/10;
refused by policy 0. The pass count is unchanged from `r1` at 4 of 10, and the same four cases.

What did move is how two failures are *classified*, and one of those is a finding against us. EXP-10
went from `unsupported` to `failed / budget_exhausted`, which is the more accurate of the two. EXP-05
went from `unsupported` to **`failed / internal_error`** — the planner proposed an element reference
that was not in the view it had been sent, and the run refused rather than acting on a ref the model
invented. The refusal is right and is exactly the fail-closed control it is meant to be. The *class*
is wrong: `internal_error` means our own defect, and a model inventing a ref is not that. It is the
same species as the misattribution Amendment 26's A-14b half exists to fix, found one build too late
to correct inside the freeze. It is recorded here rather than repaired quietly after the fact.

The abstentions are the product working, not the product failing. On a site nobody has declared, the
label a value must bind to cannot be frozen in advance; when the run cannot point at a value bound to
a label it can name, there is nothing for code to re-read and it says where it stopped. Ten cases is
a small number and the interval is the file saying so.

**Test split — 8 cases, held out. Scored once, on the frozen build, at `r4`: 1 of 8.**

| | |
|---|---|
| All cases | **1 of 8** — 0.125, 95% Wilson **0.02–0.47** |
| Declared-tier cases | **1 of 4** — 0.25, 95% Wilson **0.05–0.70** |
| Failure classes | `robots_disallowed` 3 · `policy_refused` 2 · `budget_exhausted` 1 · `postcondition_unmet` 1 · one success |
| Build / split | `e82cacb9e809` / `test-set.md` `43ee8ce5…`, hash-checked before the first case |
| Ran | 2026-07-28 19:21–19:22 UTC |

**This is the number the whole submission is measured by, and it is far below the dev split's 10 of
11. That gap is the finding, not a footnote.** The cases were written by the product owner and never
seen by the engineering session — which is exactly what makes them able to disagree with us, and
they did.

What the histogram says about *why*, without opening a single case:

- **Three of eight ended `blocked / robots_disallowed`** and two more `unsupported / policy_refused`.
  Five of eight never browsed at all. The refusals are correct — they quote the rule that matched —
  but a system that refuses five of eight ordinary-looking tasks is describing its own reachable
  surface, not its accuracy. This is L-4 at scale: the policy is right and the coverage it leaves is
  the product.
- **Three tier disagreements, and they run the wrong way.** Two cases the owner declared
  `T-DECLARED` were routed to `T-EXPERIMENTAL` by the running system, and one declared `T-REFUSED`
  also landed experimental. Half the promised-tier cases did not reach the promised surface. That is
  the same defect class as OP-7's fixed product parameter — a record we promise per
  `site × operation` while the implementation recognises something narrower — and the held-out set
  found more of it than our own dev split could, because our dev cases were written by whoever knew
  what the router accepts.
- **The one declared case that ran to an answer, passed.** Of the four declared cases, one produced
  a verified answer, one exhausted its step budget, and two were mis-tiered before they got that far.

**No evidence bundles were exported for this round, and that is a gap.** Held-out results withhold
per-case detail where the file is written (S-10.4), and the bundle exporter reads that same
withheld structure — so a round with seven non-successes carried **zero** bundles, on precisely the
split whose failures are most worth inspecting. The runs and their artifacts exist in the scored
service's own store; nothing exported them. Recorded here rather than discovered by a grader who
clicks through and finds an empty directory.

**Validation split — NOT RUN, deliberately.** Its purpose was to keep the engineering session honest
*during* development by holding cases back from it. Development is over, so running it now buys a
number instead of the discipline it existed for (Amendment 25). Reported as unrun with this reason
rather than quietly omitted.

**The two hard gates, on these sets.** Verified-but-wrong = **0**: across all three rounds, no run
returned a value the independent re-check found to be different from what the artifact contains — and
in `r3` that statement has one case behind it where a right answer was actually *derived* rather than
merely re-located (DEV-01, 8 cells, agreed). Evidence
coverage: every claim marked verified carries the artifact id and SHA-256 it was re-extracted from.

Both statements are narrower than they look, and the narrowing is the important part:

**What the oracles actually check (A25.4).** The dev set's case notes described independent oracles —
*"the harness fetches the table, applies the same sort key, compares"* — that were never implemented.
What `check_evidence` does is re-fetch the artifact, re-hash it against the recorded digest, and
re-locate each claimed value inside it: a real independent check of *the evidence supporting the
claim*, and **not** a derivation of the right answer. On `r1` that left `independently_checked` at
**0** for OP-4 and OP-5 — the two records §4 calls structurally shortcut-proof — because their values
are structures rather than strings to search for, so "verified-but-wrong = 0" was unfalsifiable
exactly where it mattered most.

**OP-4 now has the derivation, and `r3` is the first round it ran in.** The harness fetches the
article itself, finds the table carrying the named column, decides numerically-versus-lexicographically from that column's own values, sorts, and
compares the top row; a disagreement is a finding on the case. That decision is the trap DEV-02 was
written around — sorted as text, CIK `0000001800` and `0000320193` order differently from their
numbers, and both orderings look completely reasonable on the page.

**OP-5 still has none**, and the report says so rather than implying one: expanding a collapsed box
is state that exists only after an interaction, so a plain fetch would disagree with a correct run.
Every case's `oracle` field in `eval/dev-set.md` now names which of three things checks it —
*derived independently*, *evidence re-check*, or *trace inspection* — instead of all fifteen claiming
the first.

**What we expected of the held-out set, and what happened.** We expected declared records to behave
as the matrix says and unseen tasks to abstain more often than they answer. Half the declared-tier
cases never reached the declared surface at all, and the dominant outcome was refusal before
browsing rather than abstention after looking. The prediction was wrong in a specific, useful way:
we had measured how well the system answers the tasks it accepts, and not how many reasonable tasks
it accepts. `r4` is the measurement of the second thing, and it is the one a grader will feel.

---

## 7. Known limitations

The live list is at **<https://wf-agent.zeabur.app/support>**, and it is not prose. Each entry is **a task you can type
into the box**, plus what the system actually does with it and why. Every entry has been executed
against the deployed system and reproduces as written — this was not true two days ago, which is
itself the point of the rule.

| | The task | What happens |
|---|---|---|
| **L-1** | *"In the S&P 500 constituents table on Wikipedia, sort by CIK ascending and tell me which company is first."* | Stops before browsing: `unsupported / policy_refused`. The article is described, not named, and picking a starting page the task never named is how a run answers a question nobody asked. **Naming it does not finish the job either** — *"In the List of S&P 500 companies article on Wikipedia, …"* now reaches the right table and sorts it, then fails to recognise that the sort landed and spends its remaining steps re-searching for the article: `failed / budget_exhausted`. Both halves are executed against the deployment; an earlier version of this entry claimed the second one succeeded. |
| **L-2** | *"How many books are listed on the last page of the Nonfiction category on books.toscrape.com?"* | Runs out of step budget while paging and stops with **no answer** (`failed / budget_exhausted`). Paging to "the last page" costs a model call per page. The budget is fail-closed on purpose: the alternative is reporting whichever page it reached as though it were the last. |
| **L-3** | *"Is there any book in the Fiction category on books.toscrape.com priced over £50?"* | Reads 20 of the listing's own count of 65 and reports coverage **unproven** (`unverified`). Absence is only concluded from positive proof, and a multi-page category spans several artifacts while this build verifies against one. Single-page categories are answered. |
| **L-4** | *"Use Wikipedia's search page to find articles mentioning 'convertible arbitrage'."* | Refuses before navigating (`blocked / robots_disallowed`) and quotes the robots rule. Wikipedia disallows `/wiki/Special:Search`. The refusal is correct **and** it is a limitation: an ordinary question with no permitted route has no answer here. |
| **L-5** | *"On developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/flat, tell me the Chrome version listed in the browser compatibility table."* | Browses, then abstains (`unsupported / postcondition_unmet`) naming the step, the page and the unsatisfied part of the postcondition. The value sits in a grid whose label is an icon and a column position rather than text, so there is nothing for code to re-read. Whether an unseen page yields a bindable label is a property of the page — the experimental split measures that rate rather than asserting it. **This entry replaced a Project Gutenberg task that had started succeeding**; publishing an abstention that no longer happens is the same defect as publishing a remedy that never worked. |
| **L-6** | *"Go to the nonfiction category listing on books.toscrape.com and read the second page of results, without the planner."* | Answers correctly (`succeeded_verified`) — but **on the deterministic path**. Both paths satisfy the same postcondition and are verified identically, but no model is in that loop, so it is not evidence of self-correction. Every run records its path and rates are reported per path. |
| **L-7** | *"Search the fixture catalogue for a term that appears on no page"* | **Proves the absence** (`no_result_verified`): the empty-state element is located and the counter echoes the frozen term. The limitation is what stands behind that — **a page with no empty-state element**, where an abstention may have been caused by our own page reduction dropping the element rather than by the site. Those runs are audited and badged, and the audit only covers what we thought to look for. |

**What executing the list actually found.** `python -m eval.limitations_check --base-url
https://wf-agent.zeabur.app` runs every entry, and the remedy phrasing where one is claimed, against
the deployed system and writes `eval/results/limitations-<sha>.json`. The first time it ran, **four
of seven entries did not reproduce as written**:

- L-1's remedy failed, as above — the defect the independent review found.
- L-4 published `policy_refused`; the run ends `robots_disallowed`, which is the more accurate class.
- L-5's Project Gutenberg task had started **succeeding**. An abstention published after it stopped
  happening is the same defect as a remedy published after it stopped working, so the entry moved to
  a page that does abstain (MDN's compatibility grid, whose label is an icon and a column position).
- L-7's fixture search now **proves** absence via the empty-state element instead of abstaining.

It also caught a regression in this repository that no test had: the accessibility snapshot added by
Amendment 24 took its own trace entry, every trace entry charges the step budget, and capture-heavy
runs therefore had half the browsing headroom they were designed with. One capture is one step again.

**And one more, found by scoring the same split twice.** DEV-04 passed in `r1` and failed in `r2` on
inputs that had not changed. The cause was not the operation: the run's frozen target was
`/wiki/Apple_Inc`, the evidence came from `/wiki/Apple_Inc.`, and the navigation step recorded where
the page was *at the instant `page.url` was read*. A correct run failed the check that its evidence
came from the planned page, against its own artifact.

The first fix — record the response's URL, which cannot depend on timing — was wrong, and how it was
wrong is the interesting part. Measured with a browser rather than assumed, `/wiki/Apple_Inc` answers
**200 with no redirect at all**; the address bar changes about two seconds later, from the site's own
script. Pinning the gate to the response would have made a flickering failure a permanent one. The
real defect was that one frozen target compared against one recorded endpoint can only pass every
redirect or fail every one. **Amendment 26** splits it into two assertions over three recorded values
— where the evidence came from, and whether that landing is accounted for from the plan's target by a
redirect chain or the document's own declared canonical URL. The fixture carries a case for each,
including a route that reaches the right page by a door the plan never opened. Full account in the
analysis report §5.4.

The list is only worth something if it is executable. It is now, and it stays that way — the check is
re-run before submission, and its report is committed beside the eval results.

**OP-7's parameter, now generalised.** The record promises *"open a product detail page and extract
a labelled field"* on books.toscrape.com, and the plan behind it was fixed to one product — so
asking for the UPC of any other book was the same operation and landed on T-EXPERIMENTAL. A record
is `site × operation` with the page as a parameter, and a promise the implementation narrows is a
false support matrix, not a tier-label detail: a grader's own task asking for a supported operation
would mostly have missed the supported surface.

The product now comes from the task and the run reaches it the way a person would — from the listing,
paging forward, **bounded to 6 pages**. The site has no search. A title that is not in those pages
ends `unsupported / postcondition_unmet` naming the bound and suggesting the category, which is the
remaining limitation and is stated rather than dressed up. OP-4, OP-5 and OP-6 were checked for the
same defect and take their article, column, direction, category and page from the task already.

### What is not built, and is not claimed

Each of these is a decision taken with two days left and a fixed budget, recorded as a decision
rather than discovered as a gap. Amendment 25 is where each one was made — except the last, which is
built to a stated minimum and whose bounds are the entry.

- **Task 2 (SEC 10-K extraction) is not built.** `docs/task2-seam.md` is a complete, frozen contract
  for it — the resolution rules, the amendment ordering, the cap behaviour, the hashing — and nothing
  behind that contract exists. The assignment requires one task, and a fully specified interface to a
  product that will not exist is a straight subtraction from the one that will. It is published as a
  *designed, not built* seam because the design is real work and pretending otherwise would be the
  opposite of the point.
- **Self-maintenance (§8, locator memory) is the reduced version.** A table on the volume keyed by
  `(origin, operation, role)`, written back **only** from `succeeded_verified` runs — never because
  a click worked — with a 14-day confirmation window, quarantine after three consecutive failures,
  counters on `/healthz`, and the run page badging each interaction *from memory* / *healed* /
  *freshly derived*. What is stored is an element's identity and never a value, and a remembered
  locator is re-resolved and re-verified like any other: it saves search effort, never proof. Not
  built: cross-site generalisation, ranking, a learned selector model, or memory as a first resort —
  it engages where a locator has stopped resolving. The frontend derives the claim from the code, so
  the page cannot sell it if it is removed.
- **The mutation suite is two mutations, not nine.** MU-4/5/7/9 and the sweep are cut. Two working
  mutations plus one healing demonstration is evidence; nine is a research programme, and the
  marginal mutation buys nothing the first two have not already shown.
- **The safety suite is not built.** What exists — the egress guard, robots enforcement, the refusal
  taxonomy — is load-bearing and tested. What does not exist is a safety split or an injection
  detector, so `injection_detected` is a declared status no code path currently reaches, and
  `/coverage` says so rather than leaving it to be assumed.
- **Spend controls stopped where they were.** Every spend total in this repository is generated into
  one file, [`docs/spend-ledger.md`](docs/spend-ledger.md), because three documents each carrying
  their own figure meant three figures that went stale on the same day — and a fourth written in
  words rather than digits would have gone stale just as quietly. The ceiling, the ledger and the
  credential topology are done, and the ledger is where a reader sees how over-done.
- **Runtime `blocked` detection is built to its minimum, and the two halves have deliberately
  different powers.** Pre-browse refusal of authentication and payment tasks ends `unsupported /
  policy_refused` before any navigation — *we do not do this kind of thing*. An obstacle met
  **during** a run is *something stopped us*, and ends `blocked`. **HTTP 401/403/429 ends the run**:
  the status is on the response, it needs no heuristic, and it is not a judgement about what the
  page contains. **A visible login form does not.** It only *reclassifies* a run that was already
  failing as `locator_not_found` or `postcondition_unmet` — the exact misattribution this exists to
  correct, and the one direction in which the rule being wrong costs nothing. The reason for that
  asymmetry is that a visible password field shows a login form is *present*, not that content was
  replaced by one; a page offering a sign-in beside its content looks identical, and letting that
  end a run would turn a live experimental case into a `blocked` on a coincidence. Recognising a
  paywall by how it looks is not attempted at all.

---

## 8. Policy and safety

- **Read-only.** No form submission outside the fixture, no authentication, no writes.
- **`robots.txt` is enforced**, not consulted — RFC 9309 matching semantics with a dedicated CI job.
  A disallowed path produces `blocked / robots_disallowed` with the rule quoted.
- **Every navigation re-resolves and re-checks the destination IP.** Private and loopback ranges are
  refused, including via redirect, and the refusal names the range. The cases are in
  `tests/test_policy.py` — loopback, RFC 1918, link-local `169.254.169.254`, IPv4-mapped private,
  CGNAT, and the non-http schemes — plus a startup failure if the guard is ever switched off in
  production. That is a test file, not the safety split §7 says is not built: there is no injection
  detector and no adversarial sweep.
- **Page text is untrusted data and can never alter goal, tier, policy, budget or memory.**
- **Only public data is sent to the model provider**, behind a local gate that blocks credentials,
  tokens and private URLs before egress.
- **No credential appears in any log, trace, or prompt record.** Keys load from files that are
  outside version control.
- All sites used are public, and all evaluation cases are authored by us against public pages.

---

## 9. Repository map

| Path | What is in it |
|---|---|
| `app/` | The system. `postcondition.py` freezes, `executor.py` browses, `verifier.py` is the gate, `suspicion.py` audits quiet results, `memory.py` is the locator memory, `robots.py` + `egress.py` are the policy boundary |
| `fixture/` | Our own site — POST-only search, JS pagination, blocking overlay, injection page. Exists so the hard interactions are reproducible without depending on a third party |
| `eval/` | Harness, dev and experimental splits, results, provenance, `oracles.py` (OP-4's independent derivation), `spend_ledger.py` (the one spend total) |
| `docs/task1-spec.md` | The frozen engineering spec and its amendments. **The reasoning trail is here** |
| `docs/task1-discovery.md` | The original discovery reasoning, deliberately never updated |
| `docs/analysis-report.md` | Performance, cost, scalability, and how correctness is verified |
| `docs/task2-seam.md` | Task 2's contract — designed, deliberately not built (Amendment 25) |
| `prompts/` | Every prompt given to every session, verbatim |

---

<!--
Every FILL in this file has been filled from committed measurements. Do not soften any claim in
§1, §4, §5 or §7 to make a number look better. If a claim here is no longer true of the built
system, the claim is the defect — fix the system or change the sentence, and say which in the
commit message.
-->

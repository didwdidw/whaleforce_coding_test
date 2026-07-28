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
pytest                                    # 528 tests, ~20 s (a real browser runs
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

| ID | Site | Operation | Why it is hard | Status, from `dev-deploy-e1d13cae4926-r1` |
|---|---|---|---|---|
| OP-4 | en.wikipedia.org | Sort a sortable wikitable by a named column, read a cell from the new top row | Client-side sort: the DOM order changes, the URL does not, so the answer cannot be obtained by fetching a URL | **2 of 3 dev cases as expected.** The third (DEV-02) names the article by description rather than by title and correctly stops before browsing — see L-1 |
| OP-5 | en.wikipedia.org | Expand a collapsed section/navbox and read a value not visible beforehand | The value is not in the DOM-visible state until a real interaction happens | **2 of 2.** No independent oracle: correctness here rests on our own verifier (A25.4) |
| OP-6 | books.toscrape.com | Navigate a category, page through it, extract list-level facts | Multi-page state, and the honest answer often requires proving coverage | **2 of 3.** The third exhausts the step budget on a long category and returns no answer — L-2 |
| OP-7 | books.toscrape.com | Open a product detail page and extract a **labelled** field (UPC, Availability, Price excl. tax) | The answer is a label→value binding, not a string that happens to appear | **2 of 2 in `r1`**, when the record was fixed to one product. It now takes the product from the task and reaches it by paging the listing, bounded to 6 pages — a title beyond that ends `unsupported` naming the bound rather than reporting the wrong book |

Two of the six *evidence findings* in that round were the harness disagreeing with itself, not the
product: it re-checked values against rendered text only, and `books.toscrape` carries long titles in
the `title` attribute. The product read the attribute, which is the better behaviour. The fix is
committed and `r2` re-measures with it as the only change; `r1` stays as the record.

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
Claiming general capability is easy and unfalsifiable. Declaring seven records with evidence, and
measuring everything else separately as best-effort, is the falsifiable version of the same claim.
The cost is that our headline rate covers a smaller surface than a vaguer product would advertise.

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
Seven statuses, fifteen failure classes, extended only by a written amendment. `partial` and
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
change to the spec is a numbered amendment appended to frozen text, twenty-five of them, each with
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

The round below is `r1`, the first scored against the deployment: commit `e1d13cae4926`, model
`gemini-3.1-flash-lite`, paid tier, dev split `8f584218…`, experimental split `790d9440…`.

**Dev split — 15 cases, 14 declared.** Twelve of the fourteen ended in a status the case declared
acceptable. The two that did not are both the product refusing rather than guessing: DEV-02 stops
before browsing because the article is described and not named (L-1), and DEV-08 exhausts its step
budget paging a long category and returns no answer (L-2).

The **headline pass rate is lower than that — 6 of 11** — because a case passes only when the status
is as expected *and* the harness can re-locate every verified value in the stored artifact. Four
cases were demoted by the harness's own defect: it searched rendered text only, and the site carries
long titles in the `title` attribute the product correctly read. The fix is committed and re-measured
as `r2`, with the scorer as the only change, so the difference between the two rounds is attributable.
`r1` stays as the record rather than being re-run away.

**Experimental split — 10 cases, all on sites we had never touched.** Attempted 10/10; **verified
3/10** (95% Wilson interval **0.11–0.60**); **abstained after looking 5/10**; failed or blocked 2/10;
refused by policy 0.

The abstentions are the product working, not the product failing. On a site nobody has declared, the
label a value must bind to cannot be frozen in advance; when the run cannot point at a value bound to
a label it can name, there is nothing for code to re-read and it says where it stopped. Ten cases is
a small number and the interval is the file saying so.

**Test split — 8 cases, held out.** Run once against the deployment at submission; the score, its
interval and the provenance block go in `docs/analysis-report.md`. With n=8 a single case moves the
rate by 12.5 points, which is why it is reported with an interval and not as a percentage.

**Validation split — NOT RUN, deliberately.** Its purpose was to keep the engineering session honest
*during* development by holding cases back from it. Development is over, so running it now buys a
number instead of the discipline it existed for (Amendment 25). Reported as unrun with this reason
rather than quietly omitted.

**The two hard gates, on these sets, first-run.** Verified-but-wrong = **0**: no run in `r1` returned
a value the independent re-check found to be different from what the artifact contains. Evidence
coverage: every claim marked verified carries the artifact id and SHA-256 it was re-extracted from.

Both statements are narrower than they look, and the narrowing is the important part:

**What the oracles actually check (A25.4).** The dev set's case notes described independent oracles —
*"the harness fetches the table, applies the same sort key, compares"* — that were never implemented.
What `check_evidence` does is re-fetch the artifact, re-hash it against the recorded digest, and
re-locate each claimed value inside it. That is a real independent check of *the evidence supporting
the claim*, and it is **not** an independent derivation of the right answer.

The consequence, stated plainly: for OP-4 and OP-5 — the two records §4 calls structurally
shortcut-proof — `independently_checked` was **0** in `r1`, because their values are structures (a
sort state, a table row) rather than strings to search for. So "verified-but-wrong = 0" is currently
**unfalsifiable on our two strongest records**. An OP-4 oracle that fetches the table, applies the
sort key and compares the top row is the fix, and the numeric-versus-lexicographic distinction is
exactly what DEV-02's case was written around. OP-5 has no independent ground truth and the analysis
report says so rather than implying one.

**Held-out cases will be run against this system by the graders.** What we expect: declared records
behave as the matrix says; unseen tasks on unseen sites land on T-EXPERIMENTAL, browse, and abstain
more often than they answer. The abstentions are the product working.

---

## 7. Known limitations

The live list is at **<https://wf-agent.zeabur.app/support>**, and it is not prose. Each entry is **a task you can type
into the box**, plus what the system actually does with it and why. Every entry has been executed
against the deployed system and reproduces as written — this was not true two days ago, which is
itself the point of the rule.

| | The task | What happens |
|---|---|---|
| **L-1** | *"In the S&P 500 constituents table on Wikipedia, sort by CIK ascending and tell me which company is first."* | Stops before browsing: `unsupported / policy_refused`. The article is described, not named, and picking a starting page the task never named is how a run answers a question nobody asked. **Naming it does not finish the job either** — *"In the List of S&P 500 companies article on Wikipedia, …"* now reaches the right table and sorts it, then fails to recognise that the sort landed and spends its remaining steps re-searching for the article: `failed / budget_exhausted`. Both halves are executed against the deployment; an earlier version of this entry claimed the second one succeeded. |
| **L-2** | *"How many books are listed on the last page of the Nonfiction category on books.toscrape.com?"* | Runs out of step budget while paging and stops with **no answer**. Paging to "the last page" costs a model call per page. The budget is fail-closed on purpose: the alternative is reporting whichever page it reached as though it were the last. |
| **L-3** | *"Is there any book in the Fiction category on books.toscrape.com priced over £50?"* | Reads 20 of the listing's own count of 65 and reports coverage **unproven** (`unverified`). Absence is only concluded from positive proof, and a multi-page category spans several artifacts while this build verifies against one. Single-page categories are answered. |
| **L-4** | *"Use Wikipedia's search page to find articles mentioning 'convertible arbitrage'."* | Refuses before navigating and quotes the robots rule. Wikipedia disallows `/wiki/Special:Search`. The refusal is correct **and** it is a limitation: an ordinary question with no permitted route has no answer here. |
| **L-5** | *"On www.gutenberg.org, find the 'Science Fiction' bookshelf and tell me how many ebooks it lists."* | Browses, then abstains naming the step, the page and the unsatisfied part of the postcondition. On a site never seen, the label cannot be frozen in advance, so sometimes there is nothing for code to re-read. Whether it succeeds is a property of the page — the experimental split measures that rate rather than asserting it. |
| **L-6** | *"…the nonfiction category listing, second page, without the planner."* | Answers correctly — **on the deterministic path**. Both paths satisfy the same postcondition and are verified identically, but no model is in that loop, so it is not evidence of self-correction. Every run records its path and rates are reported per path. |
| **L-7** | *"Search the fixture catalogue for a term that appears on no page"* | May abstain because **our own page reduction** dropped the element, not because the site lacked it. Runs are audited for that condition and badged. The audit only covers what we thought to look for. |

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
rather than discovered as a gap. Amendment 25 is where each one was made.

- **Task 2 (SEC 10-K extraction) is not built.** `docs/task2-seam.md` is a complete, frozen contract
  for it — the resolution rules, the amendment ordering, the cap behaviour, the hashing — and nothing
  behind that contract exists. The assignment requires one task, and a fully specified interface to a
  product that will not exist is a straight subtraction from the one that will. It is published as a
  *designed, not built* seam because the design is real work and pretending otherwise would be the
  opposite of the point.
- **Self-maintenance (§8, locator memory) is the reduced version — and check the support page for
  whether it shipped.** The planned scope is a keyed store on the volume, written back only from
  `succeeded_verified` runs, with a TTL, quarantine after three consecutive failures, and the run
  page saying whether a locator came *from memory*, was *freshly derived*, or was *healed*. Not:
  cross-site generalisation, ranking, or a learned selector model. This is the largest single gap in
  the submission and it is stated as one. The frontend does not take our word for it: the support
  page derives the claim from whether the code exists, so if it is not built the page says the
  trade-off is *intended* rather than made.
- **The mutation suite is two mutations, not nine.** MU-4/5/7/9 and the sweep are cut. Two working
  mutations plus one healing demonstration is evidence; nine is a research programme, and the
  marginal mutation buys nothing the first two have not already shown.
- **The safety suite is not built.** What exists — the egress guard, robots enforcement, the refusal
  taxonomy — is load-bearing and tested. What does not exist is a safety split or an injection
  detector, so `injection_detected` is a declared status no code path currently reaches, and
  `/coverage` says so rather than leaving it to be assumed.
- **Spend controls stopped where they were.** Total provider spend across every scored round is
  **USD 0.0477**. The ceiling, the ledger and the credential topology are done and were over-done
  relative to a bill that size.
- **Runtime `blocked` detection (login walls, 401/403/429 mid-run) is not built.** Pre-browse refusal
  of authentication and payment tasks *is* — those end `unsupported / policy_refused` before any
  navigation. What is missing is recognising an obstacle met *during* a run, which currently lands in
  `locator_not_found` or `postcondition_unmet` and therefore misclassifies rather than mismeasures.

---

## 8. Policy and safety

- **Read-only.** No form submission outside the fixture, no authentication, no writes.
- **`robots.txt` is enforced**, not consulted — RFC 9309 matching semantics with a dedicated CI job.
  A disallowed path produces `blocked / robots_disallowed` with the rule quoted.
- **Every navigation re-resolves and re-checks the destination IP.** Private and loopback ranges are
  refused, including via redirect. An SSRF probe is part of the safety suite.
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
| `app/` | The system. `postcondition.py` freezes, `executor.py` browses, `verifier.py` is the gate, `suspicion.py` audits quiet results, `robots.py` + `egress.py` are the policy boundary |
| `fixture/` | Our own site — POST-only search, JS pagination, blocking overlay, injection page. Exists so the hard interactions are reproducible without depending on a third party |
| `eval/` | Harness, dev and experimental splits, results, provenance |
| `docs/task1-spec.md` | The frozen engineering spec and all 25 amendments. **The reasoning trail is here** |
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

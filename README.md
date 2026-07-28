# Task 1 — Generalized Browser Automation Agent

Give it a task in plain English. It runs the task in a real browser against public, read-only pages,
and returns either **a verified answer with the evidence used to verify it**, or **an honest
non-success status that says what it could not do**.

It is built for one user: someone who would rather have no number than a wrong one.

**Live system:** ⟨FILL-1: public URL⟩
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

Open ⟨FILL-1⟩, type a task, watch it run. The homepage carries pre-executed runs — including
failures — that are inspectable immediately, so nothing depends on a cold container starting.

The API, if you prefer:

```bash
curl -X POST ⟨FILL-1⟩/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"task": "On books.toscrape.com, open A Light in the Attic and tell me its UPC."}'

curl ⟨FILL-1⟩/api/runs/{run_id}          # status + result + evidence bundle
curl ⟨FILL-1⟩/api/runs/{run_id}/events   # SSE progress stream
```

### Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium

⟨FILL-2: the exact env vars needed for a local run — provider key file path, fixture URL,
storage dir — as a copy-pasteable block⟩

./entrypoint.sh                    # app on :8000
ROLE=fixture ./entrypoint.sh       # fixture site, separate process
```

No LLM credential is required to see the system work: the fixture records (OP-1…OP-3) and the pinned
demonstrations run on the deterministic path.

### Tests and evaluation

```bash
pytest                                    # ⟨FILL-3: test count⟩ tests
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

| ID | Site | Operation | Why it is hard | Status |
|---|---|---|---|---|
| OP-1 | fixture | Search the catalogue via a POST-only form | No URL shortcut exists — the form must actually be submitted | ⟨FILL-4⟩ |
| OP-2 | fixture | Reach result page *N* via the JS pagination control | Pagination changes state without changing the URL | ⟨FILL-4⟩ |
| OP-3 | fixture | Dismiss a blocking overlay, then act on what it covered | The underlying control is unactionable until the overlay is gone | ⟨FILL-4⟩ |
| OP-4 | en.wikipedia.org | Sort a sortable wikitable by a named column, read a cell from the new top row | Client-side sort: the DOM order changes, the URL does not, so the answer cannot be obtained by fetching a URL | ⟨FILL-4⟩ |
| OP-5 | en.wikipedia.org | Expand a collapsed section/navbox and read a value not visible beforehand | The value is not in the DOM-visible state until a real interaction happens | ⟨FILL-4⟩ |
| OP-6 | books.toscrape.com | Navigate a category, page through it, extract list-level facts | Multi-page state, and the honest answer often requires proving coverage | ⟨FILL-4⟩ |
| OP-7 | books.toscrape.com | Open a product detail page and extract a **labelled** field (UPC, Availability, Price excl. tax) | The answer is a label→value binding, not a string that happens to appear | ⟨FILL-4: and see §7 — this record's parameter generalisation is the open item⟩ |

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

⟨FILL-5: this section is written by the engineering session from committed results — see
docs/analysis-report.md, and keep the two documents consistent. Required content:

- dev split (15 cases, committed at eval/dev-set.md): result table by record and status
- experimental split (10 cases, committed at eval/experimental-set.md): result table, and the
  abstention rate stated as a correct outcome rather than a failure
- test split (8 cases, held out until submission): first-run score with git SHA, model ID and
  eval-set hash, plus the interval — with n=8 one case is 12.5 points and the report must say so
- validation split: reported as NOT RUN, with the Amendment 25 reason
- the two hard gates: verified-but-wrong = 0, evidence coverage = 100%, stated as "on these sets,
  first-run" and never as a system-level guarantee
- what the oracles actually check per record (A25.4), including where there is no independent
  ground truth⟩

**Held-out cases will be run against this system by the graders.** What we expect: declared records
behave as the matrix says; unseen tasks on unseen sites land on T-EXPERIMENTAL, browse, and abstain
more often than they answer. The abstentions are the product working.

---

## 7. Known limitations

The live list is at **⟨FILL-1⟩/support**, and it is not prose. Each entry is **a task you can type
into the box**, plus what the system actually does with it and why. Every entry has been executed
against the deployed system and reproduces as written — this was not true two days ago, which is
itself the point of the rule.

| | The task | What happens |
|---|---|---|
| **L-1** | ⟨FILL-6: L-1 is being rewritten — Amendment 25. Fill from the corrected entry⟩ | |
| **L-2** | *"How many books are listed on the last page of the Nonfiction category on books.toscrape.com?"* | Runs out of step budget while paging and stops with **no answer**. Paging to "the last page" costs a model call per page. The budget is fail-closed on purpose: the alternative is reporting whichever page it reached as though it were the last. |
| **L-3** | *"Is there any book in the Fiction category on books.toscrape.com priced over £50?"* | Reads 20 of the listing's own count of 65 and reports coverage **unproven** (`unverified`). Absence is only concluded from positive proof, and a multi-page category spans several artifacts while this build verifies against one. Single-page categories are answered. |
| **L-4** | *"Use Wikipedia's search page to find articles mentioning 'convertible arbitrage'."* | Refuses before navigating and quotes the robots rule. Wikipedia disallows `/wiki/Special:Search`. The refusal is correct **and** it is a limitation: an ordinary question with no permitted route has no answer here. |
| **L-5** | *"On www.gutenberg.org, find the 'Science Fiction' bookshelf and tell me how many ebooks it lists."* | Browses, then abstains naming the step, the page and the unsatisfied part of the postcondition. On a site never seen, the label cannot be frozen in advance, so sometimes there is nothing for code to re-read. Whether it succeeds is a property of the page — the experimental split measures that rate rather than asserting it. |
| **L-6** | *"…the nonfiction category listing, second page, without the planner."* | Answers correctly — **on the deterministic path**. Both paths satisfy the same postcondition and are verified identically, but no model is in that loop, so it is not evidence of self-correction. Every run records its path and rates are reported per path. |
| **L-7** | *"Search the fixture catalogue for a term that appears on no page"* | May abstain because **our own page reduction** dropped the element, not because the site lacked it. Runs are audited for that condition and badged. The audit only covers what we thought to look for. |

⟨FILL-7: add any limitation found while executing A25.1 — including, if it survives, the honest entry
for whatever OP-7's parameter generalisation does not cover⟩

**What is not built, and is not claimed:** ⟨FILL-8: the Amendment 25 cut list as shipped state —
locator memory's actual scope, whether the injection detector exists, Task 2 as a designed-not-built
seam, the mutation suite's reduced size. State each as a decision with its reason, not as an
omission.⟩

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
FILL LIST — engineering session. Everything else in this file is final prose.
  FILL-1  public URL (appears in several places)
  FILL-2  local-run env var block
  FILL-3  test count
  FILL-4  support matrix status per record, from committed eval results
  FILL-5  §6 Evaluation, written from committed results
  FILL-6  L-1 rewritten after A25.1
  FILL-7  new limitations found by A25.1
  FILL-8  shipped state of the Amendment 25 cuts
Do not soften any claim in §1, §4, §5 or §7 to make a number look better. If a claim here is
no longer true of the built system, the claim is the defect — fix the system or change the
sentence, and say which in the commit message.
-->

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
| Host | ⟨FILL-A: provider / region⟩, 2 vCPU, 4 GB RAM, no swap beyond ⟨102 MB observed — confirm⟩ |
| Browser | One Chromium process, two contexts. Not two processes — see §4 |
| Model | ⟨FILL-B: pinned model ID⟩ |
| Build under measurement | ⟨FILL-C: git SHA⟩ |
| Measurement files | `eval/results/`, `docs/m0-*`, `docs/m1-report.md`, `docs/m3-model-comparison.md` |

---

## 2. Runtime performance

### 2.1 Latency

⟨FILL-D: fill from committed results. Report **per path**, because mixing them describes neither:

- deterministic path (declared records, no model in the loop): median / p90 end-to-end
- model-driven path: median / p90 end-to-end
- and the split within it — how much is provider time, browser time, verification time

Verification cost deserves its own line: the whole design rests on re-resolving inside stored
artifacts, so the report should say what that costs. If it is cheap, say so — it is a real finding
that the honesty mechanism is not the expensive part.⟩

### 2.2 Cold start

Two numbers, because they answer different questions and conflating them was a defect we corrected:

| | Measured |
|---|---|
| **Deploy to usable** — a push landing, the container building, the app answering | **112–176 s** |
| **Interruption to a user already using it** — the window where requests fail rather than queue | **12–23 s** |
| **First request to a cold-but-deployed container** | ⟨FILL-E⟩ |

The second number is the one that matters to a grader, and it is an order of magnitude smaller than
the first. It was measured externally rather than from inside the process being restarted — a
process cannot time its own unavailability.

The mitigation is design, not money: the homepage carries pre-executed runs, including failures, that
are inspectable with no container work at all (S-11.5). A grader's first impression is never an
unexplained spinner. We accepted cold start rather than paying to avoid it.

### 2.3 Throughput and load

⟨FILL-F: from `eval/loadtest.py`. Concurrency 2, queue depth 2, HTTP 429 with `Retry-After` beyond
that. Report: sustained rate at concurrency 2, behaviour at the queue limit, and confirm the 429
path is a designed state in the UI rather than an error page. Several runs fired back-to-back is a
stated grader behaviour (S-11.10b) and must be shown to be designed, not lucky.⟩

### 2.4 Memory — the binding constraint

| | |
|---|---|
| Peak observed under load | **2,320 MB** of 4 GB |
| Swap | flat at 102 MB — the system did not fall into swap under measurement |
| Headroom | ⟨FILL-G⟩ |

Memory, not CPU and not money, is what caps concurrency here. Two browser **contexts** in one process
rather than two processes is the decision that makes concurrency 2 fit; the measurement is why the
number is 2 and not 4.

---

## 3. Cost

### 3.1 Measured

| | |
|---|---|
| Median cost per model-driven run | **USD 0.0019** |
| Full dev evaluation round (r1) | **USD 0.0477** |
| Total spend across all development | **USD 0.0477** ⟨FILL-H: confirm final figure⟩ |
| Runs on the deterministic path | **USD 0** — no model call |

Every figure is billed spend. A ledger that counts free-tier usage at notional prices measures
something real but it is not money, and treating the two as the same nearly blocked our public demo
after ~125 runs having spent nothing. Both are tracked; only one is called cost.

### 3.2 What the number depends on

⟨FILL-I: state the conditions, because the figure is invalidated when they change:

- the output cap in force when it was measured (raising it invalidates the figure)
- the snapshot reduction that determines input size — this is the dominant term
- how many model calls a typical run makes, and what a recovery adds
- what a re-ask costs, since re-asks count against both budget and cost⟩

### 3.3 The honest framing

At USD 0.0019 a run, **cost is not this product's constraint and we should not pretend it was
engineered as though it were.** The interesting cost question is the opposite one: what would have to
be true for this to get expensive. That is the scalability section.

We over-invested here. Roughly five of the twenty-five spec amendments concern spend ceilings,
ledgers and credential topology, protecting a total outlay under five cents. That is recorded in §6
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

**What does not.** ⟨FILL-J: be specific and unflattering:

- the single volume holding artifacts — growth rate per run, and what the retention story is
- provider rate limits as the real ceiling above ~⟨n⟩ concurrent model-driven runs
- per-site politeness constraints (SEC's 10 req/s, crawl delays) which cap throughput per site
  independently of our capacity
- anything measured that degrades non-linearly⟩

**What would change the design at 100× volume.** ⟨FILL-K: one honest paragraph. The likely answer is
that the deterministic path scales and the model-driven path does not, and that the declared-record
architecture is exactly the thing that makes volume affordable — say it plainly, with the caveat that
it only covers surfaces someone has declared.⟩

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
| Verified-but-wrong claims = 0 | ⟨FILL-L⟩ |
| Required-evidence coverage on `verified` results = 100% | ⟨FILL-L⟩ |

**These hold on our evaluation sets, on first runs. They are not a system-level guarantee**, and any
wording implying otherwise is a defect by our own spec. With n=8 on a held-out split, one failure
moves the rate 12.5 points; the interval is reported, never a bare point estimate.

### 5.3 What the oracles actually check — and where there is none

⟨FILL-M: per record, state what independently verifies correctness, and where nothing does.

This is the most important paragraph in the report and it must be written against the code, not
against intent. Until Amendment 25 the dev set declared oracles that were never implemented — the
harness re-hashed the artifact and string-matched inside it, so on OP-4 and OP-5 the number of
independently checked claims was zero and the "verified-but-wrong = 0" gate was unfalsifiable on our
strongest evidence.

Required:
- OP-4: the implemented independent oracle — fetch the table, apply the sort key, compare the top
  row. The numeric-versus-lexicographic trap is the case's whole point.
- OP-5: state plainly that correctness rests on the product's own verifier with **no independent
  ground truth**, and what that means for the claim.
- every other record: what the harness actually does.

Disclosing a gap costs a paragraph. Being found to have declared an oracle that never ran costs the
argument.⟩

### 5.4 Verifying the verifier

A system whose central claim is "our checks are real" has to expect the checks themselves to be
wrong. Five defects of that exact shape were found and fixed during development, all the same
species — **a check that reported on a coincidence**:

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

⟨FILL-N: mutation results — detection, repair, and write-back correctness on the two retained
mutations, plus the one healing demonstration on an archived real-page DOM. State how many mutations
were retained and that the sweep was cut (Amendment 25), with the reason.⟩

### 5.5 Silent failure — the metric we actually care about

Loud failures are cheap: the run says what it could not do and a reader believes it. A silent failure
is a plausible wrong answer, and it is the only outcome that damages the user.

⟨FILL-O: report the silent-failure count across every split and every suite, with the definition
used, and how each one that occurred was found. If the number is zero, say by what method it would
have been detected had it been non-zero — a zero produced by an instrument that cannot register the
event is not a result. `app/suspicion.py` audits quiet results against the reduction log for exactly
this reason: an abstention caused by our own page reduction is indistinguishable from an honest one
unless someone checks, and that audit only covers what we thought to look for.⟩

---

## 6. What we traded away

Stated as decisions with reasons, because a submission that lists only what it built is not being
honest about a two-day calendar.

| Cut | Why |
|---|---|
| **Task 2 entirely** | The assignment requires one task. `docs/task2-seam.md` is frozen as a designed-not-built contract. A fully specified interface for a product that will not exist is a straight subtraction from the one that will |
| **The validation split** | Its purpose was to keep the engineering session honest during development. Development ended. Test is run once against the deployment; validation is reported as unrun, with this reason |
| **The mutation sweep (9 → 2 mutations)** | Two working mutations plus one healing demonstration is evidence. Nine is a research programme |
| **Most of the safety suite** | Reduced to ⟨FILL-P: what actually exists⟩. The rest is declared not built rather than implied |
| **Further spend-ceiling and ledger work** | Total spend USD 0.0477. It was done, and it was over-done |
| **Locator memory's full scope** | Reduced to ⟨FILL-Q: shipped scope⟩. Self-maintenance is a named requirement of the assignment; present, small and honestly bounded beats absent |

**Process finding, stated against ourselves.** Six of the last eight spec amendments concerned the
measuring apparatus — ledgers, budget ceilings, evaluation provenance, the spec's own change
discipline — rather than what the product can do. The instinct that produced them is the same one
that found all five broken checks in §5.4, and it is genuinely the most valuable thing in this
repository. It also became the failure mode: while it was auditing the instruments, nobody audited
the promises, which is how a false limitation and a support matrix that overstated a record both
survived to a live deployment. The correction was to run the deployed system as an adversary instead
of reading the code.

---

<!--
FILL LIST — engineering session. Fill from committed measurement files only; if a number
is not committed, either commit the measurement or write "not measured" with the reason.
Never fill a slot with an estimate presented as a measurement.
  FILL-A host/region     FILL-B model ID        FILL-C git SHA
  FILL-D latency         FILL-E cold arrival    FILL-F throughput/429
  FILL-G memory headroom FILL-H final spend     FILL-I cost conditions
  FILL-J what doesn't scale                     FILL-K 100x
  FILL-L gate results    FILL-M oracles (most important)
  FILL-N mutation results FILL-O silent failures
  FILL-P safety suite as shipped                FILL-Q locator memory as shipped
-->

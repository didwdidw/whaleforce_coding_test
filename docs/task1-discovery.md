# Task 1 — Discovery

Status: **discovery only, not frozen.** No architecture is committed here. This document exists to
(a) establish traceability to the source requirement, (b) surface genuinely different product
directions before a shape is chosen, and (c) collect the open decisions that must be answered before
a frozen spec can be written.

Source of truth: `task_description/Whaleforce-AI-Coding-Test-EN.md`. The ZH version is used only for
cross-checking; where they differ, EN wins and the difference is recorded in §1.2 rather than
silently reconciled.

---

## 1. Requirement traceability

### 1.1 Traceability matrix

Every row is a requirement lifted from the EN source. "Implication" is the PM reading of what it
forces us to build; "Evidence" is what an independent acceptance owner would have to see to mark it
satisfied. Nothing here is invented — items with no source line are marked as PRINCIPLE (supplied by
the product owner, subordinate to the source doc).

#### Common requirements

| ID | Requirement (EN source) | Implication for Task 1 | Acceptance evidence |
|---|---|---|---|
| R1 | AI-assisted workflow; they care how AI was used to reason, implement, evaluate, iterate | AI use must be visible across all four phases, not just code generation | Prompt records show planning + eval + iteration, not only "write me a function" |
| R2 | Public repo, commit history reflecting the actual development process | Incremental commits; no squashing the process away; no retroactive history | `git log` shows plausible development arc with失敗/修正 visible |
| R3 | Every submitted task presented through a **publicly accessible web frontend**; API-only is not acceptable; must be operable or inspectable from a browser | A deployed UI is a hard deliverable, not a nice-to-have. Deployment must be budgeted from day one | Live URL; grader can drive it without local setup |
| R4 | `prompts/` folder in repo root with key prompts — "we will actually read them" | Already established (see `CLAUDE.md`); prompts are a graded artifact | `prompts/` populated per session, verbatim |
| R5 | README: how to run, key design decisions, where AI helped | README is a deliverable with three mandatory sections | README present with all three |
| R6 | Analysis report: runtime performance, cost, scalability, correctness verification | Requires instrumentation from the start (latency, token/$ per run, success rate). Cannot be back-filled honestly | Report with real measured numbers from real runs |
| R7 | "Public or self-created **material** only" | No proprietary datasets, no scraped private content, no copied third-party code without right to use | Provenance of eval set and any vendored assets |

#### Task 1 requirements

| ID | Requirement (EN source) | Implication | Acceptance evidence |
|---|---|---|---|
| T1.1 | Accepts **natural language task descriptions** | Input is free-form text, not a form with a site dropdown. A site picker may exist as an affordance but must not be the only path | Grader types a sentence; system acts |
| T1.2 | Reliably executes them **across different sites** | Multi-site is mandatory; single-site depth alone fails | ≥N distinct domains demonstrated (N to be fixed in spec) |
| T1.3 | **Self-correction** — diagnose the cause on failure and try different strategies | Requires an explicit failure-cause taxonomy and a strategy selector keyed on cause. Blind retry is explicitly disqualified (G1) | Trace shows: failure → diagnosed cause → *different* strategy → outcome |
| T1.4 | **Self-maintenance** — detect UI or selector changes and **adjust locator strategies dynamically** | Requires locator health detection + re-derivation + (ideally) persistence of the repaired locator | Demo where a locator is deliberately broken and the system heals and records it |
| T1.5 | Build your own evaluation set, **covering diverse domains and task types** | Eval set is a first-class deliverable with two dimensions of diversity | Versioned eval set in repo with case metadata |
| T1.6 | Frontend accepts tasks, shows execution **progress/results**, and makes **failures inspectable** | Failure inspection is called out separately — a spinner + final answer is not enough. Need step traces, screenshots/DOM snapshots, and the diagnosed cause | Grader can open a failed run and understand *why* it failed |
| T1.7 | "We will verify with our own **unseen tasks**" | The system must degrade gracefully, and must not claim success on tasks outside its competence | Out-of-scope input produces an honest refusal/abstention, not a fabricated answer |
| T1.8 | README/frontend must list which websites are supported and what operations each supports | Capability disclosure is a deliverable | Explicit support matrix |
| T1.9 | README/frontend must list which sites/task types are problematic, unreliable, or unsupported, **with concrete examples** | Must publish real failures with real examples | Known-limitations list with reproducible cases |

#### Graded emphases ("what we'll look at" + level A)

| ID | Emphasis | Consequence for design |
|---|---|---|
| G1 | Substance of self-correction / self-maintenance — *"not just try/except retries"* | The recovery layer is the centrepiece of the build, not a wrapper. Design must be legible as a mechanism |
| G2 | Depth of the evaluation set | Eval depth is scored independently of system quality. Budget real time for it |
| G3 | **Silent-failure prevention** | A confidently wrong answer is worse than an honest failure. Needs verification + abstention as a product behaviour |
| G4 | Analysis of runtime performance, cost, scalability, correctness verification | Instrumentation is a functional requirement |
| E1 | Held-out tests run against the **deployed** system using data outside our eval set | The deployed system must be robust and available; local-only quality is worthless |
| E2 | They read code, documentation, and prompt records | Code legibility and doc quality are graded |
| E3 | Level A wants: eval depth, **layered/weighted tradeoffs**, concrete perf/cost/scalability numbers, honest failure modes, high-quality prompt records | "Layered" argues for a tiered architecture where cheap paths run first and expensive paths are earned |

#### Product-owner principles (PRINCIPLE — subordinate to the above)

| ID | Principle | Consequence |
|---|---|---|
| P1 | Audience: internal quant researchers / data scientists | Output should be usable as data (structured, citable), not just chat prose. Tolerance for latency is higher than consumer UX; tolerance for wrong numbers is near zero |
| P2 | Public, read-only tasks only. No login, private data, transactions, external writes, or anti-bot-defended sites | Site allow-list discipline; refusal path for out-of-policy tasks. This *removes* a whole class of demo risk and should be stated publicly as a deliberate scope choice, not hidden |
| P3 | LLM provider/model chosen by a config variable; Gemini during development; private-data handling needs a future data-safety gate | Provider abstraction from commit one; no vendor-specific calls sprinkled through the codebase |
| P4 | Capability disclosure must be honest; must not imply "all websites work" | Reinforces T1.8/T1.9; also means the UI itself should signal scope, not just the README |

### 1.2 EN ↔ ZH differences

No contradictions found. Five wording differences are material enough to record; in every case the EN
text is the operative one and the ZH text is either narrower or less specific.

1. **R7 scope — "material" vs "資料".** EN says "Public or self-created **material** only"; ZH says
   "僅使用公開或自建的**資料**" (data). EN is broader and covers code/assets/prompts, not just data.
   → Operating rule: apply the broader EN reading to everything we vendor, not only to the eval set.

2. **T1.4 — "adjust **locator strategies** dynamically" vs "動態調整".** EN names *locator strategies*
   as the thing that must adapt; ZH only says "adjust dynamically". EN is the stronger, more specific
   requirement. → We must be able to point at locator-strategy adaptation specifically, not merely at
   "the agent replans".

3. **T1.7 — "our own unseen **tasks**" vs "自己設計的任務驗證它在**未見過的情境**下的表現".** ZH adds
   "unseen *situations/contexts*", which reads as a stronger generalisation claim (possibly unseen
   *sites*), while EN literally says unseen *tasks*. This is the single most scope-relevant
   difference: it decides whether we optimise for depth on declared sites or breadth on arbitrary
   sites. → Raised as Open Question Q1; **not** resolved unilaterally.

4. **E3 — "layered/**weighted** tradeoffs" vs "分層與權衡".** EN's "weighted" implies we should show
   explicit prioritisation (what we sacrificed and why), not merely that the system has layers.
   → The analysis report needs an explicit "what we traded away" section.

5. **Task 2 framing — EN "so they can be consumed independently" vs ZH "讓它們能被獨立取用".**
   Equivalent, but EN's "consumed" reads more like a downstream-system contract than a UI feature.
   Relevant only to §3.

---

## 2. Product directions

Three directions that differ in *what the product is*, not just in implementation detail. They are
not mutually exclusive at the code level, but they lead to different acceptance criteria, different
eval sets, and different demos — so one must lead.

### Direction A — Curated depth: skill library + healing

**The product:** a reliable operator over a small, declared set of public research-relevant sites
(e.g. Wikipedia, Hacker News, arXiv, SEC EDGAR full-text search, a public price/econ data site).
For each site the system holds *learned, verified procedures* ("skills") — a recipe of steps and
locator strategies. A generic agent loop exists only as a fallback for anything unknown.

- **User value (P1):** high. A quant gets repeatable, near-deterministic retrieval on the sources
  they actually use. Repeatability is the value, not novelty.
- **Proof of real browser automation:** medium-high. Real navigation and DOM interaction, but a
  sceptic can ask "is this just a scraper with an LLM in front?" Must be answered by showing the
  skill being *learned* and *repaired* live, not hand-written.
- **Self-correction (T1.3):** strategy switch within a known site (alternate route to the same data,
  alternate locator family, alternate page).
- **Self-maintenance (T1.4):** *strongest of the three.* Skills carry health checks; a broken locator
  triggers re-derivation from the accessibility tree/DOM, verification, and write-back with version +
  provenance. This is a demonstrable mechanism, which is exactly what G1 asks for.
- **Silent-failure risk (G3):** low-medium. Skills can encode expected result shapes, so violations
  are detectable. Risk is *stale* skills returning a valid-looking but wrong field after a redesign —
  mitigated by health checks.
- **Evaluation (T1.5/G2):** easiest to make deep — per-site regression suites, plus deliberate
  breakage tests. Risk: eval diversity looks narrow if the site list is small.
- **Public demo (R3):** most reliable; predictable runtimes, cacheable.
- **Latency/cost:** lowest. A matured skill can run with few or zero LLM calls; LLM cost concentrates
  in learning and healing.
- **Main trade-off:** exposure on T1.7/held-out testing. If graders hand it a site outside the list,
  the fallback tier is what gets judged, and it will look thin. Honest disclosure (P4/T1.8/T1.9)
  softens this but does not eliminate it.

### Direction B — Open-domain generalist agent

**The product:** no per-site knowledge at all. A perception→plan→act loop over the accessibility
tree/DOM (plus screenshots when needed) that attempts any public read-only task on any site.

- **User value:** medium. Impressive coverage, but a quant cannot depend on it for a recurring job
  because variance is high run-to-run.
- **Proof of real browser automation:** highest. Nothing is pre-wired; every run is genuine
  interaction.
- **Self-correction:** the loop itself is the mechanism — but this is also the trap. "The agent
  replans" is uncomfortably close to "retry with a different prompt", which G1 warns against unless a
  real diagnosis step drives strategy selection.
- **Self-maintenance:** philosophically trivial (nothing hardcoded can break) — which reads as
  *dodging* T1.4 rather than satisfying it. Would need a synthetic demonstration (mutate a page, show
  the locator strategy adapting) to earn the point.
- **Silent-failure risk:** **highest.** Open-domain agents excel at producing plausible answers from
  the wrong page. Requires the heaviest verification investment.
- **Evaluation:** broad but shallow unless graded per-step; pass/fail on end answers hides where it
  went wrong. Also the hardest to keep stable — the live web changes under the eval set.
- **Public demo:** riskiest. Cloud IP blocks, CAPTCHAs, cookie walls, slow pages. P2 excludes
  anti-bot sites, which helps, but "any site" invites exactly those.
- **Latency/cost:** highest — many model calls per run, vision tokens dominate.
- **Main trade-off:** maximum ambition, maximum chance of landing at level C ("only the happy path
  works") when graders test it live.

### Direction C — Evidence-first research agent

**The product:** framed by *task type* rather than by site. The user asks a research question in
natural language ("what was the closing figure reported on page X", "list the titles on the front
page of Y", "find the filing date of Z's latest 10-K"); the system returns a **structured answer plus
an evidence bundle** — source URL, timestamp, the DOM/text region the answer came from, a screenshot,
and a confidence/abstention verdict from an *independent* verification path.

- **User value (P1):** highest for the stated audience. Quants can't use an answer they can't audit;
  an evidence bundle is directly consumable and is also the natural upstream artifact for Task 2 (§3).
- **Proof of real browser automation:** high — evidence bundles contain screenshots and DOM regions
  that only real interaction produces.
- **Self-correction:** driven by *verification failure*, not just exceptions: if the verifier can't
  confirm the claim, the executor is re-dispatched with a different strategy. This is a genuinely
  different trigger from "the click threw an error" and is the most defensible answer to G1.
- **Self-maintenance:** needs to be added deliberately (it doesn't fall out of the framing) — likely
  by borrowing A's healing skill library for the sites it uses most.
- **Silent-failure risk (G3):** **lowest by construction** — this direction is *designed around* G3,
  which is one of only four named grading emphases.
- **Evaluation:** deepest available. Each case can be scored on answer correctness *and* evidence
  correctness (did it cite the right region?), which catches "right answer, wrong reason" — a level-A
  differentiator.
- **Public demo:** good. Evidence bundles make the frontend genuinely inspectable (T1.6) instead of a
  log viewer.
- **Latency/cost:** medium-high — verification roughly doubles model spend on the verified path.
  Mitigable by verifying only claims that matter or that scored low confidence.
- **Main trade-off:** it is narrower than "any web task" — it optimises for *retrieval/extraction*
  tasks over *multi-step transactional* tasks. Under P2 (read-only, no login, no writes) that is
  arguably not a loss at all, but it must be disclosed honestly rather than presented as full
  generality.

### Comparison

| Axis | A · Curated depth | B · Open-domain | C · Evidence-first |
|---|---|---|---|
| Value to quant users | High (repeatable) | Medium (unreliable) | **Highest (auditable)** |
| "Really browser automation?" | Medium-high | **Highest** | High |
| Self-correction substance (G1) | Good | At risk of "just replanning" | **Best (verification-driven)** |
| Self-maintenance substance (T1.4) | **Best (healing skills)** | Weak / needs synthetic proof | Needs A's mechanism bolted on |
| Silent-failure risk (G3) | Low-medium | **High** | **Lowest** |
| Eval depth ceiling (G2) | Medium (narrow) | Medium (shallow) | **High (2-axis scoring)** |
| Held-out robustness (T1.7/E1) | Weak outside list | **Best in principle** | Good within task family |
| Public demo reliability (R3) | **Best** | Worst | Good |
| Latency / cost | **Lowest** | Highest | Medium-high |
| Failure mode if we run out of time | Narrow but solid → B grade | Broken demo → C grade | Fewer sites but honest → B+/A- |

### PM recommendation (for discussion, not a decision)

Lead with **C as the product framing**, implement **A as the execution tier** for the declared sites,
and keep **B's generic loop as an explicitly-labelled fallback tier** that is allowed to abstain.
That composition is also the literal reading of E3's "layered/weighted tradeoffs": three tiers, cheap
first, expensive earned, with an honest boundary between them. The two named grading emphases most
often failed by prototypes — G1 substance and G3 silent failure — are the two this composition is
strongest on. The cost is generality on transactional tasks, which P2 already excludes.

---

## 3. Task 2 boundary (high level, no schema)

Task 2 (SEC 10-K item-level extraction) consumes documents. Task 1 acquires documents. The clean cut
is **acquisition + provenance belongs to Task 1; document structure understanding belongs to
Task 2.** Concretely, Task 1 should be built so it can hand downstream:

1. **A retrieved artifact with provenance** — the raw bytes exactly as served, plus source URL,
   retrieval timestamp, and a content hash. Task 2 must never need to re-crawl to know what it read.
2. **A stable artifact address** — a run/artifact identifier that another pipeline can dereference
   later. This is what makes Task 1's output *consumable independently*, mirroring Task 2's own
   wording.
3. **A normalised text/DOM view alongside the raw bytes** — Task 1 already needs this for its own
   verification; exposing it saves Task 2 from rebuilding an HTML→text layer. Task 1 must **not**
   apply document-type-specific segmentation (no Item 1/1A/7 logic) — that is Task 2's job, and
   leaking it into Task 1 would couple the two.
4. **The run/trace + job orchestration substrate** — queue, status, retries, step traces. Task 2's
   frontend needs the same "submit → progress → inspect failure" shell (its requirement is
   near-identical to T1.6), so this should be built as shared infrastructure, not Task-1-specific.
5. **The confidence / abstention vocabulary** — Task 2 must surface "extraction confidence or failure
   cases". If Task 1 invents a coherent confidence model now, Task 2 inherits it instead of inventing
   a second, inconsistent one.
6. **The eval harness pattern** — case definition → run → judge → scored report. Both tasks need this
   and both are graded on eval depth.

One concrete bridge worth noting: **SEC EDGAR is public, read-only, and policy-compliant under P2**
(it requires a declared User-Agent, which is a courtesy requirement, not an anti-bot defence). Making
EDGAR one of Task 1's supported sites means Task 1's demo naturally produces exactly the artifacts
Task 2 will consume — without designing any Task 2 logic now.

Explicit non-goals for this round: no field schema, no item taxonomy, no storage format decision.

---

## 4. Proposed agent/session workflow and acceptance independence

The grading reads prompt records (E2) and expects the history to reflect real process (R2), so the
session structure is itself part of the deliverable. Proposed structure — **not yet created, not yet
executed**:

| Session | Role | Reads | Produces | Must NOT see |
|---|---|---|---|---|
| **S0 · PM / Spec** (this one) | Product owner + acceptance owner | Source doc | Discovery → frozen spec, acceptance criteria | — |
| **S1 · Eval authoring** | Test designer | Frozen spec only | Eval set + rubric, incl. a **sealed** held-out slice | Implementation code and traces |
| **S2..Sn · Implementation** | Engineering agent, one session per milestone | Frozen spec, open eval slice | Code, per-milestone self-check | The sealed eval slice |
| **SA · Acceptance** | Independent acceptance runner | Frozen spec + deployed system as a black box | Pass/fail report per acceptance criterion | Implementation session transcripts |
| **SR · Analysis/report** | Analyst | Measured run data | README + analysis report (R5/R6) | — |

Independence rules that make acceptance meaningful:

- **The implementer never authors the acceptance criteria, and never sees the sealed eval slice.**
  Otherwise the eval measures memorisation, exactly the failure mode E1's held-out testing exists to
  catch.
- **The system must not be its own judge.** The verifier should run with a different model/config
  than the executor, and deterministic checks are preferred to model judgement wherever a
  deterministic check exists. If a model judges, its rubric is fixed in advance in the frozen spec.
- **Frozen means amended, not edited.** Once the spec is frozen, changes are appended as numbered
  amendments with a reason. This keeps R2's honest history and prevents the spec from quietly drifting
  toward whatever got built.
- **Every session logs prompts verbatim per `CLAUDE.md`.** The prompt record is graded (R4/E2).
- **Milestones are acceptance-gated**: a milestone is done when its stated criteria pass on the
  deployed (not local) system, since E1 tests the deployment.

---

## 5. Open questions (blocking the frozen spec)

Answers to these change scope, architecture, or acceptance. Principles P1–P4 are settled and not
re-asked.

**Q1 · Generality target — depth vs breadth.**
The EN text says graders use "unseen **tasks**"; the ZH text says "未見過的**情境**" (§1.2 item 3).
Which do we design and accept against?
 (a) *Depth:* a declared site list, deep reliability, generic fallback allowed to abstain honestly.
 (b) *Breadth:* any public read-only site, accepting higher variance and higher silent-failure risk.
 (c) *Tiered:* declared sites get a guaranteed reliability bar; unknown sites get best-effort with a
 visibly different confidence label.
This single answer determines the eval set shape, the support matrix, and the headline acceptance
metric.

**Q2 · Where does the browser actually run for the public demo?**
R3 requires graders to drive a live system. Options, in rising cost/complexity: (a) self-hosted
headless browser in the same container as the app; (b) a managed cloud-browser service; (c) a
hybrid where live runs are capped and the frontend also exposes recorded past runs for inspection.
This drives infra cost, concurrency limits, timeout policy, and whether a grader can trigger
unbounded live runs against arbitrary sites. Is there a budget ceiling (monthly $ and per-run $) I
should treat as a hard constraint?

**Q3 · What is the unit of output — prose answer, or structured record with evidence?**
Direction C assumes structured answer + evidence bundle + explicit abstention. That raises build cost
and makes some natural-language tasks awkward to express, but it is the main defence against G3 and
the natural upstream for Task 2 (§3). Do you want evidence-and-abstention as a **product guarantee**
(the system may say "I could not verify this"), or as a debug affordance behind the answer?

**Q4 · How much time and how many milestones do we actually have?**
Acceptance gates only work if they fit the calendar. What is the target submission date, and roughly
how many working sessions are available? Related: should the plan assume Task 2 will definitely be
attempted afterwards (→ invest more in shared infrastructure per §3 now), or treat Task 2 as
optional (→ keep Task 1 self-contained and only avoid *blocking* Task 2)?

**Q5 · How do we prove self-maintenance (T1.4) at acceptance time?**
Real UI drift is not schedulable, so the mechanism needs a reproducible demonstration. Acceptable
approaches: (a) a mutation harness that deliberately breaks locators on a captured page and shows
detection → re-derivation → verification → write-back; (b) a self-hosted test site we mutate between
runs; (c) wait for organic drift on real sites and document whatever happens. (a)/(b) are testable
and honest but use self-created material (permitted by R7); (c) is more "real" but unschedulable and
may produce nothing before submission. Which do you want as the *acceptance* proof?

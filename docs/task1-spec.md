# Task 1 — Frozen Spec v1.0

**Status: FROZEN (2026-07-26).** Everything below is normative for the engineering session and
binding for acceptance. Changes are made by appending numbered amendments in §16, never by editing
the text above them.

**Audience:** the engineering agent that implements this, and the independent acceptance reviewer
that grades it. It should be readable without having read `docs/task1-discovery.md` (that document is
the reasoning trail and is deliberately not updated).

**Keywords:** MUST / MUST NOT / SHOULD / MAY carry their usual normative meaning. Every requirement
has an ID (`S-n.m`); the acceptance checklist in §14 references these IDs.

---

## 0. Reading order for the engineering agent

1. §1 (what this is) → §2 (hard policy) → §3 (site & operation promises) — these define what "done"
   means.
2. §4–§8 — the four mechanisms that are actually being graded: evidence/verification, status,
   self-correction, self-maintenance.
3. §9–§11 — fixture, evaluation, frontend/ops.
4. §13 — milestones. **Build in milestone order. Do not start a later milestone with an earlier gate
   unmet.**
5. §15 — known risks. Read before writing the README so the honest-disclosure sections are not an
   afterthought.

Companion document: `docs/task2-seam.md` — the downstream contract. It is standalone by design.

---

## 1. Product definition

**S-1.1** The system accepts a **natural-language task description** and executes it in a real
browser against public, read-only web pages, returning either a **verified structured result with an
evidence bundle**, or an **honest non-success status**.

**S-1.2** Primary users are internal quantitative researchers and data scientists. The consequence:
an auditable result is worth more than a fluent one, and a wrong number is worse than no number.

**S-1.3** The system is **tiered**. Tier membership MUST be visible in the API response and in the
UI, and MUST be decided before execution starts:

| Tier | Meaning | Reliability promise | Counts toward headline success rate |
|---|---|---|---|
| **T-DECLARED** | The task maps to one of the promised `site × operation` records in §3 | Promised, evidenced by eval (§10) | **Yes** |
| **T-EXPERIMENTAL** | Any other public, policy-clean, read-only site | Best-effort. Abstention is a correct outcome | **No** — reported separately |
| **T-REFUSED** | Violates §2 policy | Refused before any browsing | n/a |

**S-1.4** Architecture is the composition agreed in discovery: **evidence-first product framing**,
executed by a **declared-operation tier** with learned/healing locators, falling back to a **generic
agent loop** that is allowed and expected to abstain.

**S-1.5** The system MUST NOT present T-EXPERIMENTAL results with the same visual or structural
weight as T-DECLARED results. Public-facing copy MUST NOT imply that arbitrary websites work.

---

## 2. Hard policy constraints

These are non-negotiable. A build that violates any of them fails acceptance regardless of feature
completeness.

### 2.1 Scope of tasks

**S-2.1** Public, read-only tasks only. The system MUST NOT attempt: authentication or login flows,
private/personal data, transactions or payments, any state-changing write to a third party, or any
site that presents an anti-bot challenge.

**S-2.2** On encountering a login wall, paywall, CAPTCHA, or bot-check interstitial, the run MUST
terminate as `blocked` with the appropriate `failure_class` (§5). Attempting to solve, bypass, or
evade such a control is forbidden — not merely discouraged.

**S-2.3** `robots.txt` of the target origin is treated as **binding**, not advisory. A navigation to
a Disallowed path MUST be refused (`blocked / robots_disallowed`). Verified policy facts for the
sites in scope are recorded in §3.4; the engineering session MUST re-verify them at M0 rather than
trusting this document.

### 2.2 Egress and network safety

**S-2.4** Deny-by-default egress. Only `https` (and `http` only if a target in §3 demonstrably has no
HTTPS) may be requested. `file:`, `data:`, `blob:`, `ftp:` and any other scheme MUST be blocked for
navigation.

**S-2.5** Every navigation **and every intercepted subresource request** MUST have its resolved
destination IP checked. Loopback, private (RFC1918), link-local, CGNAT, and multicast/reserved ranges
MUST be blocked. The check MUST be re-applied on redirects, not only on the initial URL.

**S-2.6** The DNS-resolve → connect gap (rebinding) MUST be acknowledged in the README as a residual
risk if the implementation cannot pin the resolved address. Do not claim complete protection.

**S-2.7** File retrieval for the Task 2 seam MUST use the server-side fetcher subject to the same
egress policy — **not** the browser's download mechanism. Browser downloads MUST be disabled.

**S-2.8** The fixture site (§9) MUST be served from its **own public hostname**. No exemption,
allow-list hole, or localhost carve-out may be added to the egress policy to accommodate it.

### 2.3 Untrusted content

**S-2.9** All text, attributes, and metadata retrieved from any web page are **untrusted data**. They
MUST NOT be able to alter the task goal, the frozen postcondition (§4.4), the tier, the egress
policy, the budget, or the locator-memory write rules.

**S-2.10** Structural enforcement is required — it is not sufficient to instruct the model to ignore
injections. At minimum: (a) goal, postcondition, and policy live outside any model-mutable state and
are re-asserted on every step; (b) the executor accepts only a fixed allow-list of action types with
validated arguments; (c) navigation targets are validated against the tier's origin policy before
being executed.

**S-2.11** When page content is detected attempting to redirect the agent's objective, the run MUST
terminate as `blocked / injection_detected` and the detection MUST be visible in the trace. Silently
ignoring it is not acceptable — the whole point is that it becomes inspectable.

**S-2.12** The README MUST state that injection is *mitigated structurally, not prevented*.

### 2.4 Secrets

**S-2.13** Secrets, API keys, tokens, environment variables, and internal URLs MUST NOT enter model
context at all. This is a structural requirement — the model context is assembled from an explicit
allow-list of fields, never from ambient configuration.

**S-2.14** A pattern-based egress gate scans every outbound provider payload as a **second** line of
defence. It MUST be described as defence-in-depth with false-positive/false-negative risk, never as a
guarantee.

### 2.5 Politeness

**S-2.15** Per-origin request pacing MUST be configurable and enforced. SEC EDGAR MUST be limited to
**≤ 1 request/second** (their published cap is 10 rps; we self-limit an order of magnitude below it).

**S-2.16** All server-side requests to SEC MUST send a `User-Agent` containing a real contact
address, per SEC's published requirement, plus `Accept-Encoding: gzip, deflate`.

**S-2.17** The system MUST NOT enumerate, crawl, or bulk-download any third-party site. Only
targeted retrieval in direct service of a user-submitted task is permitted.

---

## 3. Promised capability surface

### 3.1 The promise unit

**S-3.1** The unit of public reliability promise is a **`site × operation` record**, not a website.
An operation that has not been evaluated MUST NOT inherit any promise from another operation on the
same site.

**S-3.2** Each promised record MUST have **≥1 case in the dev split and ≥1 case in the test split**
(§10). A record without test coverage MUST be removed from the promised list before submission.

**S-3.3** If time runs short, **promised records are cut; eval splits are never cut**. Cutting a
record means deleting it from the support matrix, the UI, and the README — not quietly leaving it
untested.

### 3.2 Promised records (must-have, v1.0)

Seven records. Two real third-party sites plus the fixture.

| ID | Site | Operation | Required UI action (S-4.1) | Result type |
|---|---|---|---|---|
| **OP-1** | fixture | Search the catalogue via the POST-only form | form submission (no URL shortcut exists) | verified record set, or verified no-result |
| **OP-2** | fixture | Reach result page *N* using the JS pagination control | pagination state change **without URL change** | verified field from page *N* |
| **OP-3** | fixture | Dismiss the blocking overlay, then perform the underlying action | overlay dismissed; underlying control becomes actionable | verified field |
| **OP-4** | en.wikipedia.org (article pages) | Sort a `wikitable sortable` by a named column, read a cell from the resulting top row | client-side sort — DOM order changes, URL does not | verified cell value |
| **OP-5** | en.wikipedia.org (article pages) | Expand a collapsed section/navbox and extract a value that is not in the DOM-visible state beforehand | client-side expand | verified value |
| **OP-6** | books.toscrape.com | Navigate to a category, page through the listing, extract list-level facts | category navigation + pagination | verified list facts |
| **OP-7** | books.toscrape.com | Open a product detail page and extract a **labelled** field (e.g. Availability, Price excl. tax, UPC) | navigation from listing to detail | verified label→value pair |

**S-3.4** **OP-5 fallback.** If M0 preflight shows no stable collapsed element on a suitable article,
OP-5 is replaced by *"open the image lightbox overlay and read the caption/metadata it exposes"* —
still a client-side state change with no URL shortcut. The engineering session picks one and records
which; it MUST NOT replace OP-5 with a pure-read operation.

**S-3.5** Target articles/pages for OP-4–OP-7 MUST be chosen at M0 and pinned in the eval cases. The
system MUST NOT depend on a specific article remaining unchanged for *correctness* — the eval case
carries the expected anchor, and drift is a `failed / verification_mismatch`, which is the honest
outcome.

### 3.3 Cross-cutting behaviours (not promises — hard gates)

**S-3.6** These MUST be demonstrable regardless of which records survive:

| ID | Behaviour |
|---|---|
| **XB-1** | **Proof of absence** — when nothing matches, return `no_result_verified` backed by a deterministically located empty-state element. Never infer absence from "I didn't find it". |
| **XB-2** | **Mutation healing** — detect a broken locator, re-derive across strategy families, re-verify the identical postcondition, write back (§8). |
| **XB-3** | **Injection resistance** — the fixture injection page must not alter goal, tier, policy, or memory (§2.3). |
| **XB-4** | **Shortcut refusal** — a run that reaches the right answer while skipping a case's declared required action is scored **fail** (§4.1). |
| **XB-5** | **Out-of-scope abstention** — a T-EXPERIMENTAL or policy-violating task produces a designed refusal/abstention with an explanation, not a fabricated answer. |

### 3.4 Site policy facts (verified 2026-07-26 — re-verify at M0)

| Site | Verified fact | Source |
|---|---|---|
| en.wikipedia.org | `robots.txt` has `Disallow: /w/`, `Disallow: /wiki/Special:`, `Disallow: /api/`. **Article pages `/wiki/<Title>` are allowed.** | `https://en.wikipedia.org/robots.txt` |
| en.wikipedia.org | Consequence: Special:Search, page history, and diffs are **out of scope**. All Wikipedia operations MUST be in-article. | derived from the above |
| books.toscrape.com | No `robots.txt` (404). Site exists as a public sandbox for automation practice. | `https://books.toscrape.com/robots.txt` |
| www.sec.gov | "Current max request rate: 10 requests/second"; "The SEC does not allow botnets or automated tools to crawl the site"; declared `User-Agent` with contact required | `https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data` |
| www.sec.gov | `robots.txt`: `Disallow: /cgi-bin`, `Disallow: /search/`, **`Allow: /Archives/edgar/data`** | `https://www.sec.gov/robots.txt` |
| www.sec.gov | Consequence: the seam uses `/Archives/edgar/data` + `data.sec.gov` (sanctioned). `cgi-bin/browse-edgar` is **out of scope**. `/edgar/search/` is not Disallowed and is stretch-only. | derived from the above |
| arxiv.org | **Excluded.** `robots.txt`: `Crawl-delay: 15`, `Disallow: /search`, `/find`, `/form`, `/api`. Policy: "Indiscriminate automated downloads from this site are not permitted"; violators are denied access. | `https://arxiv.org/robots.txt`, `https://info.arxiv.org/help/robots.html` |

**S-3.7** The README MUST state plainly that `books.toscrape.com` was chosen **because its automation
policy is unambiguous**, and that arXiv was dropped **because its robots policy forbids the
operations we needed**. No repackaging as a research narrative.

---

## 4. Evidence and verification

This section is the core of the product. If anything here is weakened, silent-failure prevention
(the named grading emphasis) is lost.

### 4.1 What counts as a real browser action

**S-4.1** A **substantive UI action** is an agent-caused, observable state change on an
already-rendered page that is required by the case. It includes:

- URL or route change caused by interacting with a control,
- form state submission,
- pagination state change,
- **and, explicitly, client-side-only state changes: sort order, expand/collapse, overlay
  dismissal, tab switch, lightbox open.**

Pure navigate-then-read is **not** a substantive UI action.

**S-4.2** Every eval case declares, in advance: required actions, expected state transitions, the
postcondition, and the required evidence. The harness verifies these against the recorded action
trace.

**S-4.3** **Honesty constraint.** What the harness verifies is *"the case declared this action as
required and the trace shows it happened"*. It does **not** prove the action was impossible to
bypass. The README MUST use exactly this framing. To make the stronger claim partially true, at
least three promised records (OP-1, OP-2, OP-3) are on surfaces where no URL shortcut exists by
construction.

**S-4.4** APIs (including the sites' own JSON endpoints) MAY be used for supporting discovery or as
an oracle in the harness. A run that reaches the correct answer while skipping a declared required
action is scored **fail** (`failed / required_action_skipped`) even though the value is right. A
deliberate shortcut-taking case MUST exist in **both** the dev split and the regression suite so the
engineering session discovers the rule early rather than at acceptance.

### 4.2 The evidence bundle

**S-4.5** Every claim the system reports MUST carry an evidence bundle containing at least:

- `artifact_id` of the **saved page snapshot at the moment of extraction** (DOM + accessibility
  snapshot; screenshot where it aids inspection),
- `source_url`, `retrieved_at`, and a content hash of the artifact,
- a **structural anchor** that deterministic code can re-resolve inside the saved artifact,
- the **label anchor** — the deterministically located label/header text the value is bound to
  (§4.3),
- the extracted span and the normalised value,
- the action trace segment that produced the state the artifact was captured in.

### 4.3 The definition of `verified`

**S-4.6** `verified` means, exactly: *this claim is consistent with the source artifact we preserved
at `retrieved_at`, and it passes deterministic entity / type / date / unit checks.* It does **not**
mean the claim is true in the world. This wording MUST appear in the UI (not only the README).

**S-4.7** **The LLM may only produce candidates** — actions, locators, claims, evidence spans. It
MUST NOT be able to set `verified`.

**S-4.8** The final gate MUST be **deterministic code re-resolving the stored anchor inside the
stored artifact** and re-extracting the value independently of the model's output, then comparing.
A mismatch is `failed / verification_mismatch`.

**S-4.9** **Label→value structural binding is required.** The verifier MUST locate the label text
deterministically and obtain the value by a declared structural relation to it (same row, adjacent
cell, definition-list pairing, etc.). Checking only the *shape* of a value (looks like a date, looks
like a price) is insufficient and MUST NOT be the sole check.

**S-4.10** A second LLM MAY act as an adjudicator with exactly one power: **reject / downgrade**. It
MUST NOT promote anything to `verified`.

**S-4.11** Any natural-language summary produced by a model MUST be stored in a separate field and
rendered in a visually distinct region labelled as unverified model output. It MUST NOT be
interleaved with verified facts in either the data structure or the UI.

### 4.4 Postcondition freezing

**S-4.12** The postcondition is constructed at plan time, serialised, and **hashed**. The hash is
recorded in the trace. Verification re-checks against the frozen object. Any divergence between the
verified postcondition and the frozen hash is itself a failure — this is what makes "recovery may not
lower the bar" (§7) mechanically checkable rather than a slogan.

---

## 5. Terminal status taxonomy

**S-5.1** Every run ends with exactly one `terminal_status` and, unless successful, exactly one
`failure_class`. These are two orthogonal fields.

### 5.1 `terminal_status`

| Value | Meaning | Counts as success |
|---|---|---|
| `succeeded_verified` | All required claims produced and verified per §4.3 | **Yes** |
| `no_result_verified` | The correct answer is "nothing matches", proven by a deterministically located empty-state element (XB-1) | **Yes** |
| `partial` | Some required claims verified, others missing | **No** |
| `unverified` | A candidate answer exists but zero deterministic confirmation | **No** |
| `failed` | Execution or verification failed | No |
| `blocked` | Stopped by policy, an external control, or a resource limit | No |
| `unsupported` | Recognised as outside the declared+experimental envelope before/early in execution | No |

**S-5.2** `partial` and `unverified` MUST NOT be rendered, aggregated, or described as success
anywhere in the product or the report.

### 5.2 `failure_class`

`locator_not_found`, `postcondition_unmet`, `verification_mismatch`, `required_action_skipped`,
`budget_exhausted`, `timeout`, `provider_quota`, `provider_error`, `policy_refused`,
`robots_disallowed`, `site_unavailable`, `injection_detected`, `queue_full`, `session_quota`,
`internal_error`.

**S-5.3** The set is closed. Adding a value is an amendment (§16). `internal_error` is for unhandled
defects only and its rate is reported in the analysis report — a high rate is itself a finding.

---

## 6. Budgets and fail-closed behaviour

**S-6.1** Every run has hard limits, enforced and surfaced in the trace: wall-clock timeout, max
steps, and max LLM calls. Defaults (configurable; final values recorded in the analysis report):
**180 s wall clock, 25 steps, 12 LLM calls.**

**S-6.2** The LLM-call budget MUST be split into an **exploration budget** and a reserved **recovery
budget** (default 8 / 4). Exploration MUST NOT be able to consume the recovery reserve. Without this
split, runs die before they can ever demonstrate self-correction.

**S-6.3** Exceeding any budget is fail-closed: `failed / budget_exhausted` or `failed / timeout`.
Under budget pressure the system MUST NOT downgrade to `partial` or emit an unverified answer as if
it were a result.

**S-6.4** Budget exhaustion, quota exhaustion, and fallback MUST NOT relax §4.3. There is no
condition under which something is marked `verified` without passing the deterministic gate.

---

## 7. Self-correction

**S-7.1** **Retry ≠ recovery.** Re-running the *same* strategy after a transient error is a retry. It
MAY happen (bounded), and it MUST be recorded as `retry` — it MUST NOT be counted or presented as
self-correction.

**S-7.2** A **recovery** is a transition to a *different strategy family*, triggered by a diagnosed
cause. The families are closed and enumerated:

| Family | Strategy |
|---|---|
| **F1** | Semantic / accessibility: ARIA role + accessible name |
| **F2** | Text and label anchoring: visible text, `<label>`, heading proximity |
| **F3** | Structural: DOM-relative paths, table/list positional relations |
| **F4** | Visual / coordinate (screenshot-driven) — **last resort only** |
| **F5** | Alternate route or surface: a different page or navigation path to the same postcondition |
| **F6** | Alternate representation: another rendering of the same data on the same site |

**S-7.3** F4 is last resort. If no reliable element can be identified, the system MUST abstain rather
than click at coordinates speculatively. Blind clicking is prohibited.

**S-7.4** Every recovery MUST record: the diagnosed cause, the family transitioned from and to, and
the re-verification outcome against the **identical frozen postcondition** (§4.4).

**S-7.5** Recovery MUST NOT rewrite the goal, relax the postcondition, or reduce the required
evidence. If the task can only pass by lowering the bar, the correct outcome is `failed` or a
deliberate abstention.

**S-7.6** The diagnosis step MUST produce a named cause from a closed set (e.g. element absent,
element present but not interactable, obscured by overlay, content not yet rendered, ambiguous match
/ decoys, navigation blocked, content changed). "The step threw an exception" is not a diagnosis.

---

## 8. Self-maintenance (locator memory)

**S-8.1** Locator memory persists **across runs**. Within-run repair alone does not satisfy this
section.

**S-8.2** Memory entries are keyed by `(site_origin, operation_id, element_role)` and hold a ranked
list of locator candidates, each with: strategy family, version, provenance (`run_id`,
`artifact_hash`, `verified_at`), and health counters.

**S-8.3** **Write-back precondition:** an entry may only be written or promoted from a run that
reached `succeeded_verified` or `no_result_verified` **with the postcondition verified
deterministically**. Never from a `partial`, `unverified`, or model-asserted success.

**S-8.4** **Scope limit:** memory may only influence *how an element is located*. It MUST NOT be able
to affect the task goal, the postcondition, the tier, the egress or content policy, budgets, or the
verification gate. This MUST be enforced structurally — memory feeds the locator-resolution component
only and is never injected into the planner as free-form instructions.

**S-8.5** **Never a shortcut around verification.** A memory hit still requires the full deterministic
postcondition verification. Memory saves search effort, never proof.

**S-8.6** **Health and quarantine:** consecutive failures demote a candidate's rank; after N
consecutive failures (default 3) the entry is quarantined and the system falls back to fresh
derivation. Quarantined entries MUST be visible in the UI — a poisoned memory that no one can see is
worse than no memory at all.

**S-8.7** Entries carry a TTL (default 30 days) after which they must be re-verified before reuse.

**S-8.8** The UI MUST show, per run, whether a locator came from memory or was freshly derived, and
whether a healing write-back occurred.

---

## 9. Fixture site

**S-9.1** A self-built fixture site, served on its **own public hostname** (S-2.8), used for the
mutation gate and for operations that cannot be safely or reliably exercised on third-party sites.

**S-9.2** **Mutation catalogue** — all MUST be programmatically applicable and seeded:

| ID | Mutation |
|---|---|
| MU-1 | Rename all `id` / `class` attributes |
| MU-2 | Change button and label text |
| MU-3 | Insert wrapper elements / reorder DOM |
| MU-4 | Introduce two near-identical decoy elements |
| MU-5 | Delayed rendering of the target |
| MU-6 | Overlay covering the target action |
| MU-7 | Move the pagination control |
| MU-8 | Empty state (drives XB-1) |
| MU-9 | Malformed / broken markup |

**S-9.3** **Ground truth comes from the fixture's own server state via a test hook**, generated
**independently of the mutation layer**. The mutation layer MUST NOT be able to change the answer;
the fixture MUST have a self-test asserting this. The system under test MUST NOT have access to the
test hook.

**S-9.4** Mutation seeds are recorded with every run so any result is reproducible.

**S-9.5** The fixture MUST include an **injection page** whose content attempts to redirect the
agent's objective (e.g. instructing it to visit another origin or to report a different value). The
expected outcome is `blocked / injection_detected` with the attempt visible in the trace (XB-3).

---

## 10. Evaluation

### 10.1 Splits

**S-10.1** Three splits, with caps: **dev ≤ 15, validation ≤ 8, test ≤ 8**.

**S-10.2** **Repository policy:** the **dev split lives in the repo**. Validation and test **case
content MUST NOT be committed**. The repo holds only their case counts and a content hash. The
authored validation/test cases are delivered to the product owner out-of-band.

**S-10.3** The engineering session sees dev only. It MUST NOT see validation or test case content.

**S-10.4** **Validation feedback channel:** validation is executed by the harness on behalf of the
product owner during the engineering session. The engineering session receives **only** the aggregate
score and the `failure_class` histogram — never case content, never per-case detail.

**S-10.5** **Coverage rule:** every promised record in §3.2 has ≥1 dev case and ≥1 test case. Test
also includes at least one T-EXPERIMENTAL abstention case (XB-5).

**S-10.6** **First-run rule:** a held-out split's score is the result of its **first** execution
against the deployed system. After it has been inspected it is a regression suite and MUST be called
that — never "held-out" again.

**S-10.7** Every first run MUST record: **git SHA, pinned model ID, eval-set content hash**, plus
timestamp and deployment identifier. A score without this provenance is not reportable.

### 10.2 Additional suites

**S-10.8** **Mutation gate suite** (fixture only, seeded, deterministic): run on every build. Measures
detection rate, repair rate, families traversed, and write-back correctness. A subset of seeds is
withheld from the engineering session.

**S-10.9** **Safety suite** (small, all-must-pass): injection page, out-of-scope site, policy-violating
task, SSRF probe against a private address, shortcut-cheat case.

### 10.3 Hard gates

**S-10.10** On the dev, validation, and test splits, measured on first runs:

1. **Verified-but-wrong claims = 0.**
2. **Required-evidence coverage for `verified` results = 100%.**

**S-10.11** These gates are stated as *"zero on these evaluation sets, first-run"* — **not** as a
system-level guarantee. Any wording that implies the latter is a defect (see §15, R-1).

**S-10.12** Gate 1 MUST NOT be relaxed for timeout, quota exhaustion, or fallback conditions.

**S-10.13** With n = 8 per held-out split, report an interval, not a bare point estimate. A single
failure moves the rate by 12.5 points and the report MUST say so.

---

## 11. Frontend and operations

### 11.1 Frontend

**S-11.1** Publicly accessible web frontend (API-only fails the requirement outright). It MUST allow:
submitting a natural-language task, watching progress, and inspecting a completed run.

**S-11.2** A run detail view MUST expose: the step-by-step action trace, the diagnosed cause of any
failure, retries vs recoveries with the family transitions, the evidence bundle per claim, the
artifact snapshots, the frozen postcondition, budget consumption, and the locator-memory
hit/derive/heal/quarantine status.

**S-11.3** Tier (§1.3) MUST be visible on both the submit form and the result. T-EXPERIMENTAL results
MUST be visually distinct and marked as not counting toward the reported success rate.

**S-11.4** The support matrix (§3.2) and the known-limitations list MUST be reachable **from the
frontend**, not only from the README.

**S-11.5** **Cold start UX:** the homepage MUST show several **pre-executed runs** that are
immediately clickable and inspectable, including at least one failure. While a container or browser
is starting, the UI MUST say specifically what it is waiting for. A grader's first impression MUST
NOT be an unexplained spinner.

**S-11.6** The definition of `verified` from S-4.6 MUST be shown in the UI where verified results
appear.

### 11.2 Runtime

**S-11.7** Self-hosted headless browser co-located with the app. No managed cloud-browser service.

**S-11.8** Concurrency 2, implemented as **two browser contexts inside a single browser process** —
not two browser processes. Queue depth 2. When full, respond **HTTP 429** with `Retry-After` and a
clear UI message (`blocked / queue_full`). No unbounded queueing.

**S-11.9** **Cost ceiling:** no resource with a fixed monthly cost above **USD 10** may be created.
Free/hobby tiers by default. **Before provisioning anything paid, stop and ask the product owner,
with alternatives.** Cold start is accepted; money MUST NOT be spent to avoid it.

**S-11.10** **Grader behaviour is a design input.** All three of the following MUST be designed
behaviours, not luck: (a) tasks we have never seen; (b) several runs fired back-to-back; (c)
undeclared sites submitted. Respectively: tier assignment with honest abstention; queue + 429 +
per-session cap; T-EXPERIMENTAL or T-REFUSED with an explanation of what was attempted.

**S-11.11** **Separate LLM credentials for the public demo and for eval runs**, so grader traffic
cannot exhaust the quota the evaluation depends on.

**S-11.12** A per-session run cap on the public demo. Exhaustion produces a designed, explained state
(`blocked / session_quota`), never something that looks broken.

**S-11.13** Provider quota exhaustion produces `blocked / provider_quota` with an explanation in the
UI.

### 11.3 LLM configuration

**S-11.14** Provider and model are selected by configuration variables (e.g. `LLM_PROVIDER`,
`LLM_MODEL_ID`). No provider-specific calls outside the provider adapter.

**S-11.15** Development and evaluation use **Gemini** with a **pinned stable model ID**. `*-latest`
aliases and preview models MUST be rejected at startup when eval mode is enabled. Rationale is
documented by Google: `latest` aliases point at the newest release, including preview/experimental.

**S-11.16** **No silent fallback.** If the pinned model is unavailable, the run fails as
`blocked / provider_error`. Changing the model requires re-running the affected cases and recording
the change.

**S-11.17** The approach is **accessibility-tree / DOM driven with a stable Flash-class text model**.
Purpose-built computer-use/coordinate models are **out of scope for v1.0**: they are preview-status
(conflicting with S-11.15) and coordinate-based action is the hardest thing to verify
deterministically, which runs against §4.

**S-11.18** Google no longer publishes per-model free-tier RPM/TPM/RPD in its rate-limit
documentation — limits are account- and tier-specific and shown in AI Studio. **This spec therefore
contains no quota numbers.** The engineering session MUST read the actual limits for the project's
key at M0 and record them in the analysis report.

---

## 12. Task 2 seam

**S-12.1** Task 1 owns **acquisition and preservation**. Task 2 owns **content understanding**. Task 1
MUST NOT contain any 10-K-specific segmentation, item taxonomy, or document-structure logic.

**S-12.2** The seam MUST be consumable without any knowledge of browser plans, locators, strategy
families, or run traces.

**S-12.3** The seam is **separately scored**. It MUST NOT be counted as browser-generalisation
coverage and MUST NOT substitute for any hard gate in §10.3.

**S-12.4** The seam MUST be exercised by an **independent consumer** — a small program written
against `docs/task2-seam.md` alone, which MUST NOT import internal modules.

**S-12.5** Full contract: `docs/task2-seam.md`. In summary: uniquely identify a filing; retrieve and
hash the **primary document** and the **complete submission text file** as bytes; keep
**inventory metadata only** for exhibits/XBRL/images; and if a cap is hit, **mark the representation
as not retrieved — silent truncation is prohibited**.

---

## 13. Milestones and engineering-session acceptance gates

Build in order. Do not proceed past a failed gate — stop and report.

| # | Milestone | Gate (all must pass) |
|---|---|---|
| **M0** | **Preflight from the deployed environment** | (a) one browser process + 2 contexts + app fit in the chosen tier's RAM under load; (b) en.wikipedia.org, books.toscrape.com, sec.gov reachable **from the deployment IP**, not just a laptop; (c) the §3.4 policy facts re-verified; (d) actual Gemini rate limits for our key recorded; (e) target pages for OP-4…OP-7 pinned. **Any failure → stop and ask, do not substitute a site or work around a block.** |
| **M1** | Walking skeleton deployed | Public URL accepts a task, runs against the fixture without any LLM, shows progress and a trace; queue + 429 behaviour correct |
| **M2** | Evidence + deterministic verifier + status taxonomy | Deterministic re-resolution on saved artifacts works; label→value binding enforced; all `terminal_status`/`failure_class` values reachable and exercised; postcondition hash frozen at plan time |
| **M3** | LLM planner, strategy families, recovery | Recoveries are cross-family and logged with a named diagnosed cause; retry and recovery are distinguishable in the trace; exploration/recovery budget split enforced |
| **M4** | Real sites | OP-4…OP-7 pass their dev cases; robots policy enforcement demonstrated on a Disallowed path |
| **M5** | Locator memory + mutation gate | Write-back only from verified success; quarantine works; mutation suite reports detection/repair/write-back rates; memory hits still verified |
| **M6** | Safety suite | Injection page → `blocked / injection_detected`; SSRF probe blocked; out-of-scope abstention; shortcut-cheat case scored fail |
| **M7** | Task 2 seam | Independent consumer retrieves a real 10-K's primary document + complete submission text with lengths and SHA-256; cap behaviour explicit |
| **M8** | Docs | README (run instructions, design decisions, where AI helped, support matrix, honest limitations) + analysis report (performance, cost, scalability, correctness verification, what we traded away) |

**S-13.1** **Minimum viable submission is M0–M4 plus M8.** M5–M7 are must-have per §3 but if the
calendar breaks, the order of sacrifice is: promised records (§3.3) first, then M7, then M6, then M5.
Hard gates (§10.3) and the honesty requirements are never sacrificed.

**S-13.2** The engineering session MUST log its prompts per `CLAUDE.md` and MUST commit at real
milestones — not once per action, and not in one squashed lump.

---

## 14. Acceptance-session checklist (independent reviewer)

The reviewer works **black-box against the deployed system plus this spec**, and MUST NOT read the
engineering session's transcripts before forming a verdict.

**Setup**
- [ ] A-1 The public URL is reachable and usable without local setup (S-11.1).
- [ ] A-2 The homepage shows pre-executed runs including a failure; cold-start messaging is specific (S-11.5).

**Honesty**
- [ ] A-3 Support matrix in the frontend matches what the system actually does; every promised record has test coverage (S-3.2, S-11.4).
- [ ] A-4 Known-limitations list contains concrete reproducible examples (T1.9).
- [ ] A-5 The `verified` definition is shown in the UI and matches S-4.6.
- [ ] A-6 Hard gates are stated as eval-set/first-run results, not system guarantees (S-10.11).
- [ ] A-7 README states the arXiv exclusion and the books.toscrape rationale plainly (S-3.7).

**Core mechanism**
- [ ] A-8 Run the test split first-run; record git SHA, model ID, eval hash (S-10.6, S-10.7).
- [ ] A-9 Verified-but-wrong = 0 and evidence coverage = 100% on that first run (S-10.10).
- [ ] A-10 Open a failed run: diagnosed cause, trace, artifacts, frozen postcondition all inspectable (S-11.2).
- [ ] A-11 Confirm at least one recovery is genuinely cross-family with a named cause, not a retry (S-7.1, S-7.2).
- [ ] A-12 Confirm no run marked `verified` without deterministic re-resolution (S-4.8) — check by tampering with a saved artifact if feasible.

**Adversarial**
- [ ] A-13 Submit a task on an undeclared site → T-EXPERIMENTAL, honest abstention or clearly-labelled best-effort (XB-5).
- [ ] A-14 Submit a login/paywalled/anti-bot target → `blocked`, no bypass attempted (S-2.1, S-2.2).
- [ ] A-15 Submit a robots-Disallowed path (e.g. a Wikipedia `Special:` page) → `blocked / robots_disallowed` (S-2.3).
- [ ] A-16 Run the fixture injection page → `blocked / injection_detected`, goal and memory unchanged (S-9.5).
- [ ] A-17 Fire 5+ runs back-to-back → queue, then 429 with a clear message; no unbounded queue (S-11.8).
- [ ] A-18 Verify the shortcut-cheat case is scored fail even though its answer is right (S-4.4).
- [ ] A-19 Verify `partial` / `unverified` are never presented or aggregated as success (S-5.2).

**Self-maintenance**
- [ ] A-20 Trigger a mutation seed; confirm detection → cross-family re-derivation → re-verification of the identical postcondition → write-back (XB-2).
- [ ] A-21 Confirm memory cannot alter goal/policy and that a memory hit still passes full verification (S-8.4, S-8.5).
- [ ] A-22 Confirm quarantine is visible in the UI (S-8.6).

**Seam**
- [ ] A-23 Run the independent consumer against `docs/task2-seam.md` only; primary document and complete submission text are retrieved with length + media type + SHA-256 + retrieved_at (S-12.4).
- [ ] A-24 Force the cap; confirm explicit not-retrieved marking, no silent truncation (S-12.5).

**Reporting**
- [ ] A-25 Analysis report contains measured latency, measured cost per run, scalability limits, correctness-verification method, and an explicit "what we traded away" section.

---

## 15. Known risks — where this will be attacked

Written by the product owner, in advance, on purpose. If a reviewer finds these, they are documented
positions, not surprises.

**R-1 · `verified` does not mean true.** The deterministic gate proves transcription fidelity to a
preserved artifact plus type/unit/date/entity conformance. A value that is correct in form but taken
from the **wrong row, wrong entity, or wrong period** can pass. Mitigated by the label→value
structural binding (S-4.9) and by cases declaring an expected anchor. **Residual gap remains and is
disclosed.** This is the single most likely place a determined reviewer draws blood.

**R-2 · Fixture-heavy promises.** Three of seven promised records are on our own fixture. A reviewer
can fairly say we set our own exam. Mitigations: real-site records carry the same gates; fixture
records are labelled as such everywhere; the fixture exists because mutation testing is otherwise
unschedulable (self-created material is explicitly permitted). We do not claim fixture results
generalise.

**R-3 · Only two real third-party sites.** "Across different sites" is satisfied thinly. A third site
is stretch, not promised. Disclosed rather than padded.

**R-4 · books.toscrape.com is an easy target.** It is a static sandbox. We chose it for policy
clarity, and we say so (S-3.7) rather than implying it was a hard technical choice.

**R-5 · "Necessary UI action" is declared, not proven** (S-4.3). Three records are structurally
shortcut-proof; the rest rely on declaration plus trace verification.

**R-6 · n = 8 held-out.** Wide confidence interval; one failure = 12.5 points. Reported as an
interval (S-10.13). We chose fewer promises over more cases deliberately.

**R-7 · Cold start.** A grader's first request may wait tens of seconds. Mitigated by pre-executed
runs and explicit messaging (S-11.5); not mitigated by spending money (S-11.9).

**R-8 · Single engineering session.** Little room for iteration. The sacrifice order in S-13.1 is
pre-committed so that scope is cut honestly rather than gates being quietly loosened.

**R-9 · Injection is mitigated, not prevented.** Page content necessarily influences the next action.
A sufficiently clever injection could still steer navigation; provenance display and origin policy
bound the damage (S-2.12).

**R-10 · Locator memory can encode a stale-but-once-verified locator.** If a site changes such that
the old locator still resolves to something plausible, memory could accelerate a wrong extraction.
Mitigated by TTL, re-verification on every use, quarantine, and UI visibility (§8) — not eliminated.

**R-11 · The experimental tier will look weak.** On a grader's unseen site it will often abstain.
That is the designed behaviour, but it can read as "doesn't work". Mitigation: the abstention must
explain what was attempted and why it stopped — an abstention with no reasoning is a product defect.

**R-12 · Free-tier quota exhaustion during grading.** Mitigated by separate demo/eval credentials,
per-session caps, and a designed `blocked` state (S-11.11–S-11.13).

**R-13 · SEC policy tension.** SEC states it does not allow automated tools to crawl the site. Our
position: the seam performs targeted, user-initiated retrieval on the explicitly `Allow`-ed
`/Archives/edgar/data` path, at ≤1 rps with a declared contact UA, and never enumerates. Documented
so the position is visible rather than assumed.

**R-14 · DNS rebinding.** Between resolve and connect, an attacker-controlled name could change
address. Disclosed (S-2.6) rather than claimed solved.

---

## 16. Amendments

Append numbered entries below; do not edit §0–§15. An amendment supersedes the text it names.

### Amendment 1 — The fixture is not a promised capability (2026-07-26)

Supersedes the promised-record table in **§3.2**.

**Rationale (product owner):** promising operations on a site we built ourselves is setting our own
exam. The fix is not more mitigation — the fixture simply is not a product capability. It is an
evaluation instrument.

**A1.1** The promised set is **OP-4, OP-5, OP-6, OP-7 only** — four records across two real
third-party sites. OP IDs are not renumbered; ID stability matters more than tidiness.

**A1.2** OP-1, OP-2, OP-3 are **withdrawn from the promised set** and become gate-suite operations
**GS-1** (POST-only form search), **GS-2** (JS pagination with no URL change), **GS-3** (overlay
dismissal then act). They are exercised on the fixture inside the mutation gate suite (§10.2) and
MUST NOT appear in the support matrix, the frontend's supported-sites list, or any success-rate
figure.

**A1.3** The frontend and README MUST state explicitly that the fixture is **our own evaluation
environment, not a supported website**, wherever the fixture is visible.

**A1.4** The freed test/validation slots go to negative cases: proof of absence, out-of-scope
abstention, and experimental-tier unknown sites. They MUST NOT be used to pad promised-record counts.

### Amendment 2 — "Across different sites" is answered by the experimental tier (2026-07-26)

Extends **§1.3** and **§3**.

**A2.1** The source requirement "reliably executes them across different sites" is **not** answered by
counting declared sites. It is answered by the **T-EXPERIMENTAL tier**: any public, policy-clean,
read-only site may be attempted; where the system cannot verify a result it abstains and says where
it got stuck. Two declared sites plus an honest experimental tier is the deliberate answer, and the
README and frontend MUST present it that way — as a chosen trade-off (depth on locator memory and
the safety suite over breadth of declared sites), not as unfinished work.

**A2.2** An experimental abstention MUST name (a) the step it stopped at, (b) the last observed page
state, and (c) why the postcondition could not be verified. An abstention without this is a product
defect, not a safe default.

**A2.3** A third real site (Project Gutenberg — `robots.txt` disallows only `/ebooks/search`) remains
**stretch**, added only after §13's must-have gates pass.

### Amendment 3 — Two proof modes for absence (2026-07-26)

Extends **XB-1** in §3.3.

**A3.1** `no_result_verified` may be reached by either mode:

- **Mode A — empty-state element:** a deterministically located element stating that nothing matched.
  Available on the fixture (MU-8).
- **Mode B — verified exhaustive enumeration:** the complete result set was enumerated, coverage is
  proven against the site's own count/pagination anchor (e.g. `"110 results - showing 1 to 20."`,
  `"Page 1 of 6"`), and the verifier re-checks from the saved artifacts that **every** member was
  seen and **none** satisfies the predicate.

**A3.2** Mode B requires a **coverage anchor**. Absence claimed without one is `unverified`, never
`no_result_verified`. "I looked and didn't find it" is not a proof of absence.

### Amendment 4 — Restatement of which surfaces are structurally shortcut-proof (2026-07-26)

Supersedes the last sentence of **S-4.3**.

**A4.1** Among the promised records, **OP-4 and OP-5 are structurally shortcut-proof**: a client-side
table sort and a collapse/expand produce no URL a shortcut could target. OP-6 and OP-7 have stable
URLs and therefore rest on declared-necessity plus trace verification (S-4.2/S-4.3).

**A4.2** Honest qualification on OP-5: on Wikipedia the collapsed content is generally *present in
the DOM* before expansion, so an agent could in principle read it without expanding. The state
transition (`aria-expanded`, visibility) is what the harness verifies. OP-5's claim is therefore
"declared and trace-verified", not "impossible to bypass". This MUST be stated in the README.

**A4.3** GS-1/GS-2/GS-3 on the fixture remain structurally shortcut-proof by construction and carry
that part of the argument — as gate evidence, not as a promise.

### Amendment 5 — Replacement for known risk R-2 (2026-07-26)

Supersedes **R-2** in §15.

**R-2 (revised) · The promised surface is narrow: two real sites, four records.** The fixture is
excluded from promises by design (Amendment 1), which removes the "graded our own exam" objection but
leaves a genuinely small declared surface. Our position: promise quality over promise count — every
promised record carries dev and test coverage, and breadth is handled by the experimental tier with
honest abstention (Amendment 2). A reviewer may still judge the declared surface thin; that is a
disclosed trade-off, not an oversight.

**R-2b · The strongest anti-shortcut evidence now sits in a suite we authored.** GS-1/GS-2/GS-3 run
on our own fixture. Mitigated by OP-4/OP-5 being structurally shortcut-proof on a real site
(Amendment 4), and by the fixture's ground truth coming from server state independent of the
mutation layer (S-9.3).

### Amendment 6 — Eval split composition and repository policy (2026-07-26)

Extends **§10.1**.

**A6.1** Split sizes as authored: **dev 15, validation 8, test 8.**

**A6.2** Composition — dev: 10 promised-record cases (OP-4 ×3, OP-5 ×2, OP-6 ×3, OP-7 ×2) plus 5
behavioural cases. Validation and test: 4 promised-record cases (one per record) plus 4 behavioural
cases each.

**A6.3** The dev split lives at `eval/dev-set.md`. Validation and test **case content is never
committed**; `eval/holdout-manifest.md` records only their case counts and content hashes.

**A6.4** Test cases MUST differ from dev cases by more than wording — at minimum by entity, page
type, operation order, or expected result type. A synonym-swapped duplicate is not a held-out case.

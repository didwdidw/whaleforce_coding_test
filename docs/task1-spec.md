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

### Amendment 7 — Token budgets, snapshot reduction, and cost accounting (2026-07-26)

Extends **§6** and **§13 M0**. Adds two values to the closed set in **S-5.2**.

**Rationale (product owner):** budgets currently count LLM *calls*. Cost and free-tier quota are
consumed by **tokens and requests**, not by call count. An untrimmed accessibility tree of a large
list article can be tens of thousands of tokens in a single call, so a 12-call budget bounds nothing
that matters.

**A7.1 Per-call input cap.** Every model call has a hard input-token cap (default: **8,000 tokens**
for the page-derived portion of the context). A call whose assembled context exceeds the cap MUST be
reduced further or fail closed — it MUST NOT be sent.

**A7.2 Snapshot reduction is mandatory.** No raw page snapshot is ever sent to a model. What is sent
is a reduced view containing: interactive elements, the target region, and text in the neighbourhood
of candidate anchors. The reduction rule has a version identifier.

**A7.3 Reduction must be recorded.** The trace MUST record, per call: the reduction rule version,
what was dropped (counts by category — e.g. rows, non-interactive nodes, script/style, off-target
regions), and a reference to the full stored artifact. Without this, a wrong answer cannot be
attributed between *the model reasoned badly* and *we trimmed away the evidence*, which is the whole
point of having a trace.

**A7.4 Verification always runs on the full artifact.** The deterministic verifier (§4.3) MUST
re-resolve anchors inside the **complete stored snapshot**, never inside the reduced view sent to the
model. Verifying against the trimmed view would make verification circular.

**A7.5 Per-run token budget.** In addition to the call budget (S-6.2), each run has a cumulative
input-token budget (default: **60,000 tokens**). Exhaustion is fail-closed, exactly as S-6.3.

**A7.6 Per-run cost accounting.** Every run MUST record: input tokens and output tokens per call and
in total, the pinned model ID, the unit prices in force (from configuration, not hard-coded), and the
computed USD cost. This is stored in the trace and displayed in the UI. Without it, acceptance item
A-25 ("measured cost per run") has no source.

**A7.7 New `failure_class` values:** `context_budget_exceeded`, `token_budget_exhausted`.

**A7.8 M0 additions.** Beyond reading the account's actual rate limits, M0 MUST measure and report:

1. **Token and cost per run** for one run on each of three page shapes: a books.toscrape category
   listing, the S&P 500 Wikipedia article (the large-DOM case), and a product detail page. Report
   input tokens, output tokens, and USD per run, at the pinned model's published prices.
2. **Requests-per-day feasibility.** A full evaluation round is dev 15 + validation 8 + test 8 = 31
   task cases, plus the mutation gate suite and the safety suite. At up to 12 model calls per run
   that is on the order of **400+ provider requests per round**, before any development iteration.
   M0 MUST report the account's actual requests-per-day limit and state plainly **how many full
   rounds fit in one day**.
3. If a full round does not fit in the free tier, **stop and report the numbers with the paid-tier
   cost of a round**. Do NOT silently spread runs across days, reduce the call budget, or switch to a
   cheaper model to fit — any of those changes the measured system.

**A7.9 Free-tier data use.** Google's published pricing states that free-tier content is used to
improve their products, and paid-tier content is not. Because v1.0 sends only public page content
(P2), the free tier is acceptable — but this MUST be stated in the README, and the future
private-data gate (P3) MUST revisit it before any non-public content is ever sent.

**A7.10 Verified prices (2026-07-26, `ai.google.dev/gemini-api/docs/pricing`).** `gemini-2.5-flash`:
input **$0.30 / 1M**, output **$2.50 / 1M**. `gemini-3.5-flash`: input **$1.50 / 1M**, output
**$9.00 / 1M**. These are configuration inputs for A7.6 and MUST be re-checked at M0 rather than
trusted from this document.

### Amendment 8 — Hosting, credentials, and spend control (2026-07-26)

Extends **§11.2**, **§11.3**, **§13 M0**, and **S-10.8**.

#### Hosting

**A8.1** Fixed monthly hosting cost stays at **≤ USD 10** (S-11.9). The engineering session picks the
provider.

**A8.2** During feature development the system MAY be served from the product owner's local machine
via **Cloudflare Tunnel**. Choosing a host is not a milestone; do not spend development time on it.

**A8.3** **M0's RAM and reachability measurements MUST NOT be taken through the tunnel.** Spin up a
real cloud container, `curl` the three target sites from it, and observe memory under load. The check
exists precisely because datacenter IPs and residential IPs are treated differently; run from a home
network it is always green, and the block is then discovered on deployment day. This is a
measurement, not a hosting commitment — the container can be destroyed immediately afterwards.

**A8.4** Cold start MUST NOT be bought away (S-11.9 unchanged).

**A8.5** The M0 report additionally states: **which host was chosen for final production and why**,
and the **measured cold-start duration**.

#### Credentials

**A8.6** Keys live in `api_keys/`, which is git-ignored: `Free_tier_agent_API_Key` (free tier) and
`Billing_agent_API_Key` (paid tier).

**A8.7** Keys are **loaded from file only**. They MUST NOT be echoed to a terminal, written to logs,
placed in a trace, included in a prompt record, or embedded in any artifact. S-2.13 already required
this; it is restated because the keys now sit beside the repository, where a careless `cat` lands the
secret in `prompts/` — a file that is deliberately published.

**A8.8** **Fallback policy.** When the free tier is exhausted, **dev and eval runs fall back to the
paid key automatically**, without asking. **The public demo path MUST NOT auto-fall-back**; its
exhaustion remains `blocked / provider_quota` (S-11.13). Two reasons: the credential separation in
S-11.11 exists so external traffic cannot consume the evaluation quota, and auto-fallback would
remove that wall entirely; and the spend ceiling below is an intent held by a person — nothing at
runtime can enforce it.

**A8.9** Each run's trace MUST record **which credential tier was used**. A7.9 discloses that
free-tier content is used by the provider to improve its products and paid-tier content is not; a
silent switch would make that disclosure inaccurate.

#### Spend

**A8.10** Provider usage is budgeted **separately** from the hosting ceiling. If M0 shows the free
tier cannot cover a full evaluation round, enable billing and proceed. The engineering session may
self-approve provider spend up to **cumulative USD 5**; beyond that, stop and ask.

**A8.11** **Model selection is an experiment, not a guess.** Run a bounded comparison across
candidate *stable* models, pick the **cheapest one whose quality is acceptable**, and record the
comparison in the analysis report. `ai.google.dev/gemini-api/docs/pricing` is the **sole** source of
truth for prices. One model is then pinned for the evaluation (S-11.15).

**A8.12** **Output tokens need a cap too.** Amendment 7 bounded input only. Output is billed
including thinking tokens, and at the verified prices output costs **8.3× input** on
`gemini-2.5-flash` ($2.50 vs $0.30 per 1M) and **6× input** on `gemini-3.5-flash` ($9.00 vs $1.50) —
so output, not input, is the dominant cost risk. Each call MUST have a max-output-token cap, each run
a cumulative output cap, and where the model exposes a thinking budget it MUST be bounded. Exceeding
is fail-closed as in S-6.3.

**A8.13** **Dev-only response cache.** The provider adapter carries a response cache keyed by a hash
of the assembled prompt. It makes re-running the same cases nearly free while iterating on memory,
the mutation layer, or the UI; changing the prompt invalidates the entry. The cache MUST be
**disabled for validation and test runs**, and every performance or cost figure reported must come
from uncached runs — otherwise the measured numbers are fiction.

**A8.14** Supersedes the "run on every build" clause of **S-10.8**: the mutation gate suite runs on a
**throttled trigger** — a full seed sweep before each milestone gate and before any acceptance run,
a small smoke subset otherwise, plus on demand. Run unthrottled it can account for a third of the
provider bill on its own.

**A8.15** **Sub-agents are for offline work only** — mutation seed generation, fixture page authoring,
batch classification of injection cases, code review. They MUST NOT appear anywhere in the product's
inference path. **Evaluation cases are authored by the product owner**; the engineering session MUST
NOT generate its own eval cases.

### Amendment 9 — Model availability, credential policy, and the M0 outcome (2026-07-26)

Extends **A7.10**, **A7.8**, **S-11.15**, **A8.8**, **A8.11**, **S-2.16**, **S-11.9**. Proposed by the
engineering session in `docs/m0-preflight-report.md` §9, approved with modifications and additions by
the product owner. §5 and §7 of that report are the evidence.

#### Model availability and the pin

**A9.1** `gemini-2.5-flash` and `gemini-2.5-flash-lite` return `404 NOT_FOUND` for this project's key
("no longer available to new users"), verified by live `generateContent` calls at M0. A7.10's prices
for `gemini-2.5-flash` remain correct as published and are retained as historical record; they are no
longer usable as configuration inputs for A7.6.

**A9.2** The pinned model for development and evaluation is **`gemini-3.1-flash-lite`** (GA, input
**$0.25 / 1M**, output **$1.50 / 1M**, verified 2026-07-26), the cheapest callable stable model.
A8.11's bounded comparison still governs the final pin and runs before M3.

**A9.2.1** **No validation or test run may be executed before the pin is final.** Both held-out
splits are scored on their first run (S-10.6) and every first run records the pinned model ID
(S-10.7). Running them against a provisional model burns a held-out run whose only value was that it
could be spent once.

**A9.3** S-11.15's startup validation MUST issue a **minimal live call**, not a `models.list()`
lookup. Both unavailable models are present in the list response and fail only on use, so a
list-based check passes and then fails at the first real call — which would surface as
`blocked / provider_error` mid-run rather than at startup.

**A9.4** A7.8's cost arithmetic is restated at the pinned model's prices: measured **$0.0011–$0.0036
per run**, ~**$0.15 per full evaluation round**, ~$0.80 per round if every run exhausted its 12-call
budget.

**A9.5** **A8.11's comparison MUST include at least one non-lite candidate.** A full round costs
~$0.15 at the lite model; a model six times more expensive costs ~$0.90, which sits well inside the
USD 5 self-approval ceiling (A8.10). **Price is therefore not a deciding variable at this scale** —
the pin is decided on the quality of locator reasoning, and A8.11's "cheapest acceptable" is settled
only after acceptability is demonstrated, not before. Within the $1.50-input band the candidate is
**`gemini-3.6-flash`** (output $7.50 / 1M), not `gemini-3.5-flash` (output $9.00 / 1M): same input
price, cheaper output, and output is the dominant cost (A8.12).

#### Credentials for scored runs

**A9.6** **Validation and test runs MUST use the paid (`Billing_agent_API_Key`) credential
unconditionally**, whether or not free-tier quota remains. This narrows A8.8: automatic free→paid
fallback still applies to development, but a scored run does not start on the free key at all.

Two reasons. First, mid-run exhaustion on a held-out split is `blocked / provider_quota` **and that
round cannot be re-run** — the split's value is that it is spent once. Second, it makes A7.9's README
disclosure clean: free-tier content is used by the provider to improve its products and paid-tier
content is not, so putting every scored run on the paid tier means **no evaluation content is ever
used for product improvement**, with no case-by-case reasoning required.

This is arithmetic, not preference. The account's free-tier limits for `gemini-3.1-flash-lite`,
read from AI Studio at M0, are **RPM 15 / TPM 250,000 / RPD 500**. Against the measured **~294
requests per full round** (report §6), `500 / 294` is **one round per day**, leaving ~200 requests for
development iteration — and a round in which runs actually spend the S-6.1 12-call budget is ~756
requests, which does not fit at all. **This closes the final open item of A7.8**; A7.8.3's
prohibition stands unchanged — the response to a tight quota is the paid key, never spreading a round
across days or trimming the call budget.

#### Unattended operation

**A9.7** **The service MUST run unattended and continuously for two weeks or more.** This is an
acceptance condition, not an aspiration: the deployed system is graded on a schedule we do not
control, and a demo that is healthy on deploy day and dead a week later scores as broken. Three
mechanisms are required:

1. **Browser lifecycle recovery.** A crashed or unresponsive browser process MUST be detected and
   relaunched without human intervention, and in-flight runs MUST terminate as an honest
   `failed` / `blocked` state rather than hanging.
2. **Bounded storage growth.** The artifact store and logs MUST have an enforced retention or size
   bound. A single large-DOM run stores ~2 MB of snapshot (report §1); unbounded, this fills the disk
   and takes the service down. Eviction MUST NOT silently break evidence bundles already referenced
   by a reported result — expiry is a recorded state, not a dangling reference.
3. **No memory growth over time.** Per-run resources (contexts, pages, listeners, temp files) MUST be
   released, and steady-state memory MUST be observed to be flat across a sustained multi-hour run,
   not merely at start-up.

#### Corrections promoted to requirements

**A9.8** **S-2.16 is a functional precondition, not politeness.** M0 measured SEC returning **403** to
a request without a declared contact `User-Agent` (report §2). The header MUST be set at fetcher
construction time so it cannot be omitted per call, and the seam's test suite MUST cover its absence
— a missing header presents as a network-level block and would otherwise be misdiagnosed as
`site_unavailable`.

**A9.9** **Wikipedia imposes no crawl-delay on us.** The `Crawl-delay: 5` in `en.wikipedia.org/robots.txt`
sits inside the `User-agent: SemrushBot` block, not `User-agent: *` (report §3). Per-origin pacing
(S-2.15) remains enforced, but the README MUST describe it as **our own voluntary limit**, and MUST
NOT present it as compliance with a robots directive. Claiming an obligation we do not have is a
false claim about our own behaviour, which is the same class of error the honesty requirements exist
to prevent.

#### Host

**A9.10** **Production host: Tencent Cloud, Ashburn (US) region — 2 vCPU / 4 GB RAM / 60 GB SSD, USD
4/month, rented through Zeabur, with Zeabur as the deployment layer.** This is within the S-11.9
ceiling of USD 10/month fixed cost and supersedes the options weighed in report §8. The 4 GB
allowance carries the measured ~794 MiB peak (report §1) with room for the second context and steady
growth, so the RAM gate is not the binding constraint the 1 GB candidates would have made it.
A8.4 is unchanged: cold start is still accepted and MUST NOT be bought away. A8.5's remaining
deliverables — the measured cold-start duration and the cloud RAM and reachability figures — are
still owed, now measured on this host.

### Amendment 10 — robots.txt matching semantics, and the egress guard's failure mode (2026-07-27)

Extends **S-2.3**, **S-2.5**, **§14**. Prompted by a real defect found at M1 and by three safeguards
the engineering session built ahead of the spec.

#### Why this exists

S-2.3 says `robots.txt` is binding. It does not say **how a rule is matched**, and that gap produced
an actual violation. The M1 implementation used Python's `urllib.robotparser`, which terminates a
user-agent group at a **blank line**. In `www.sec.gov/robots.txt` the `#SEC` block sits after a blank
line inside the `User-agent: *` group, so `Disallow: /cgi-bin` and `Allow: /Archives/edgar/data` were
both discarded. Measured result: `cgi-bin/browse-edgar` — explicitly out of scope in §3.4 — was
**permitted**. The same parser also ignored `*` and `$` and applied **first-match** rather than
longest-match.

The failure mode is the one this spec penalises most heavily: the system would have crawled Disallowed
paths **while reporting itself compliant**. A permissive robots parser produces no error, no anomaly,
and a clean trace.

**And the eval set could not have caught it.** DEV-13 (robots refusal) would have passed, because the
rule it happens to target sits *before* the blank line. A case that passes for the wrong reason is
indistinguishable from one that passes for the right one. **This class of defect is caught by tests of
the matching semantics themselves, never by dataset outcomes** — which is why A10.6 is a separate
requirement rather than a note.

#### Matching semantics (replaces the unstated behaviour under S-2.3)

**A10.1** robots.txt evaluation MUST follow **RFC 9309**. Specifically:

1. **Longest match wins.** The applicable rule is the one whose path pattern is longest, not the first
   one encountered.
2. **Ties go to `Allow`.** When an `Allow` and a `Disallow` pattern of equal length both match, the
   path is **allowed**.
3. **Wildcards are supported.** `*` matches any sequence of characters; `$` anchors the end of the
   path. A parser without these silently under-blocks.
4. **A group ends only at the next `User-agent` line.** **Blank lines and comments MUST NOT terminate
   a group.** This is the specific defect above, and it is the one most likely to recur in any
   substitute library.

**A10.2** The system MUST NOT rely on `urllib.robotparser`, which violates A10.1.1, A10.1.3 and
A10.1.4. Whatever is used in its place — a compliant library or an implementation of the above — the
behaviour is what is required, not the choice of component.

**A10.3** **Unfetchable `robots.txt` fails closed.** If `robots.txt` cannot be retrieved (network
error, timeout, 5xx, or an unparseable body), navigation to that origin MUST be refused as
`blocked / robots_disallowed`. A 404 is a valid answer meaning "no restrictions" (this is
`books.toscrape.com`, §3.4) and is not a failure to fetch. Availability of the policy file MUST NOT
become a reason to ignore the policy.

**A10.4** Every robots decision — allowed or refused — MUST record in the trace the **matched rule**
(directive, pattern, and the group's user-agent) or explicitly that **no rule matched**. A refusal
without a citable rule is unverifiable; an allow without one cannot be audited after the fact.

**A10.5** The refusal in A10.3 and A10.1 applies to **every** origin the system touches — including
the server-side fetcher used by the Task 2 seam (S-2.7), not only browser navigations. The defect
above was found on SEC, which the browser tier never visits.

**A10.6** **The robots matching semantics MUST have their own unit tests**, independent of the
evaluation dataset. Coverage MUST include, at minimum: longest-match precedence, equal-length
`Allow`/`Disallow` ties, `*` and `$` patterns, a group containing blank lines and comment lines, a
group correctly terminating at the next `User-agent`, and the fail-closed path of A10.3. The live
`www.sec.gov/robots.txt` body — the one that exposed the defect — MUST be one of the fixtures.

#### Egress guard configuration (promoting implementation to requirement)

The engineering session built three safeguards at M1 that the spec did not ask for. They belong in the
spec because **acceptance is black-box against this document**: a reviewer who cannot read the code
has no basis on which to verify them, and an unstated safeguard is one that can be silently removed.

**A10.7** **The environment defaults to production.** The environment variable selecting the runtime
mode MUST treat **unset, empty, or unrecognised values as production**, with the guard fully enforced.
Exactly one explicit value enables the relaxed development mode. Any control whose *failure* mode is
"protection off" is a control that will eventually be off.

**A10.8** **Misconfiguration refuses to start.** A configuration that cannot be resolved to a valid
mode MUST cause startup to fail loudly, not to fall back to a default and continue.

**A10.9** **Guard state is recorded per run and exposed for inspection.** The first step of every run's
trace MUST record whether the egress guard is enforcing, **including for runs that the guard itself
refused** — those are exactly the runs whose guard state a reviewer needs. The same state MUST be
readable from the health endpoint, so that "is the deployed system actually protected right now?" is
answerable without a run.

#### Acceptance additions (§14)

- [ ] **A-26** Submit a path that is Disallowed only by a rule appearing **after a blank line or a
  comment** within its group (e.g. an SEC `/cgi-bin/` path) → `blocked / robots_disallowed`, with the
  matched rule visible in the trace (A10.1.4, A10.4).
- [ ] **A-27** Confirm the robots matching semantics carry dedicated unit tests covering A10.6's
  listed cases, and that they are run in CI rather than by hand.
- [ ] **A-28** Confirm the health endpoint reports the egress guard as enforcing, and that a run's
  first trace step records the same state (A10.9).

### Amendment 11 — Persistent artifact storage, and what a volume does not fix (2026-07-27)

Extends **S-11.2**, **S-11.5**, **A9.7.2**, **A10.7**, **A10.8**. Decided at M2.

#### The decision

**A11.1** **A persistent volume MUST be mounted for the artifact store and the run database.**
Ephemeral storage is incompatible with the product's central claim: an evidence bundle whose artifact
vanished on the next deploy is a dangling reference that is only discovered when someone opens it —
which is the precise failure this spec penalises most, a result that looks sound until inspected.

**A11.2** **The accepted cost is stated, not hidden.** Zeabur switches a volume-mounted service from
`RollingUpdate` to `Recreate`, so every deployment takes a full cold start of downtime instead of an
overlapping rollout. This is accepted: **the cost is paid during development, the benefit is paid
during grading.** The analysis report MUST state this trade-off explicitly rather than presenting
persistence as free. A8.4 is unchanged — this downtime MUST NOT be bought away.

#### What a volume does not fix

**A11.3** **Pre-executed homepage runs are exempt from retention.** The S-11.5 demonstration runs MUST
be pinned: their artifacts are never evicted, by age or by disk pressure, and they are excluded from
the retention sweep entirely. Without this, a grader arriving two weeks after deployment finds that
the first screen they see is three expired links.

The alternative — re-running them on expiry — is rejected. S-11.5 requires one of the demonstrations
to be a **failure**, and a re-run reproduces neither a specific failure nor a specific verified value
reliably; a scheduled re-run that silently breaks leaves the homepage worse than stale. Pinning is
deterministic, and the set is small and bounded. The honesty cost of pinning is that the runs age:
each pre-executed run MUST therefore display its `retrieved_at` date, so a two-week-old demonstration
reads as a dated demonstration rather than as a current result.

**A11.4** **Expiry MUST render as a recorded state, never as an error.** A9.7.2 requires expiry to be
a recorded state rather than a dangling reference; in practice the bytes *will* be reclaimed, so the
requirement lands on the presentation layer. A run detail view referencing an artifact whose bytes are
gone MUST show **"expired on `<date>`"** — never a 404, a broken image, or an empty panel. The
artifact's metadata (id, source URL, `retrieved_at`, content hash, byte length, and the expiry date)
MUST survive the bytes, so the evidence bundle stays auditable in structure even when it is no longer
re-inspectable. The same applies to the API representation, not only the HTML view. **This requirement
is independent of the volume and would be required without it.**

**A11.5** **A missing or unwritable volume MUST report unhealthy.** The health endpoint MUST verify
the artifact store is actually mounted **and writable** — by an actual write probe, not by a path
existence check — and report unhealthy when it is not. Under A10.7's rule, the system MUST NOT
silently fall back to ephemeral storage: that is exactly the condition being fixed here, and it is
invisible from outside. In production mode a store that cannot be initialised is a startup failure
(A10.8).

**A11.6** **Retention MUST be enforced, and bounded by disk, not only by age.** The host has 60 GB and
artifacts are screenshots plus full DOM — a single large-DOM run stores ~2 MB (M0 report §1). The
store MUST enforce both an age limit and a **total size ceiling** set as a fraction of the disk, with
eviction oldest-first over unpinned artifacts, and MUST record each eviction. Reaching the ceiling is
an operational event that MUST be visible (health endpoint and logs), not a silent overwrite of
evidence. An unenforced retention policy is A9.7.2 in name only.

#### Two defect classes promoted to requirements

Both were found by the engineering session while writing M2 tests, and both are already fixed. They
are recorded here because the *class* is what matters, not the two instances.

**A11.7** **Vacuous verification MUST fail closed.** A postcondition with **zero claims** MUST NOT
produce `succeeded_verified`. More generally, **any verification that passes because there was nothing
to check is a defect, not a pass**: an empty claim set, zero evidence bundles, zero anchors resolved,
or an all-skipped check set MUST terminate as `failed` with a diagnosed cause, never as success.
"Nothing failed" is not "everything passed" — and this is precisely the silent-failure shape §4 exists
to prevent, since a vacuous success is indistinguishable from a real one in every aggregate.

**A11.8** **Explicit zero is not absence.** Configuration resolution MUST distinguish an
**explicitly-set falsy value** (`0`, `false`, empty string) from an **unset** one. A `0` that is
treated as missing and replaced by a default silently overrides an operator's explicit instruction —
here, `retention_days=0` became the 14-day default. This is the same family as A10.7: a control whose
misconfiguration resolves to a permissive default is a control that will eventually be off. Defaults
MUST be applied only when a value is genuinely absent.

#### Acceptance additions (§14)

- [ ] **A-29** Redeploy the service, then open a pre-executed homepage run and a completed user run
  from before the deploy: artifacts still resolve (A11.1, A11.3).
- [ ] **A-30** Open a run whose artifacts have passed retention: the view shows a dated expired state
  with metadata intact — no 404, no broken image (A11.4).
- [ ] **A-31** Confirm the health endpoint reports unhealthy when the artifact store is unwritable,
  and that retention limits (age and size) are enforced and observable (A11.5, A11.6).

### Amendment 12 — Topological credential isolation, enforced spend ceiling, store containment (2026-07-27)

Extends **A8.8**, **A9.6**, **A8.10**, **A11.1**, **S-11.11**. Decided at the M3 preflight gate; the
model pin (A9.2) is unchanged.

#### Credential isolation is topological, not conditional

**A12.1 Correction to the reasoning behind A9.6.** Two things were being conflated. The Common
Requirements have held-out cases run against the **deployed system** — that is **grader traffic**, and
it runs on the public demo path under A8.8 and S-11.13 (free credential, no auto-fallback, exhaustion
surfaces as `blocked / provider_quota`). A9.6's paid-credential requirement applies to **our own
validation and test split runs**. Only the latter needs the paid key. A9.6's conclusion stands; only
its scope is narrowed to what it actually covers.

**A12.2 The paid credential MUST NOT be present on the filesystem of the container serving public
traffic — at any point, including on the M8 acceptance day.** This is the substance of the amendment.
S-11.11 asked for separate credentials; a runtime branch that selects a credential is a condition that
can be mis-evaluated, and its failure mode is silent. Absence of the key is a property of the
environment, and it cannot be defeated by a bug in a conditional.

**A12.3 Scored runs execute as a separate workload**, co-located on the same host and built from the
same image, holding the paid credential. It **MUST NOT** be published on any public domain and MUST
NOT be reachable over HTTP from outside the host. It shares the persistent volume (A11.1) so that
evidence from scored runs lands in the same artifact store and remains inspectable through the public
run views.

**A12.4** The claim "the public service does not hold the paid key" MUST therefore be **literally
true of the process serving anonymous traffic**, and the README and analysis report MUST state it in
those terms — as a deployment topology, not as an application-level policy.

#### The spend ceiling must exist at runtime

**A12.5 A daily cumulative USD ceiling MUST be enforced in code.** A8.10's USD 5 limit currently
exists only as an intention in a person's head, while the paid credential is already in use — the gap
between "we decided a limit" and "something enforces a limit" is the whole risk. Requirements:

1. **Checked before every provider call**, not sampled, not checked afterwards.
2. **Exceeding the ceiling refuses the call** and terminates the run as `blocked / provider_quota`.
   Continuing to spend while logging a warning is not acceptable — this is fail-closed under S-6.3.
3. **The accumulated state lives on the persistent volume** (A11.1) so it survives restarts and
   redeploys. A counter held in memory resets exactly when spending resumes.
4. **The current spend and the ceiling are exposed on the health endpoint**, so the remaining budget
   is answerable without reading logs or the provider console.

#### Store path containment

**A12.6** A boundary test found a real vulnerability present since M2: retention `unlink`ed paths
taken from the database, and `read_artifact` used paths from the same source to decide what to return
over HTTP — **neither side checked ownership**. That is arbitrary file deletion plus arbitrary file
read, and 107 passing tests did not catch it. Invariants that live only in tests are invariants that
can be removed by anyone who does not read the tests.

**A12.7 Store containment is a requirement.** Every filesystem path the artifact store reads or
deletes MUST be **resolved** (symlinks and relative segments included) and MUST be verified to fall
under the artifact root directory. A path resolving outside the root MUST be refused and recorded in
the error log. Path-traversal segments MUST be rejected. This applies to **both** sides — the serving
path and the retention sweep — because either alone leaves the vulnerability open.

#### Reporting scope

**A12.8** The M8 analysis report MUST state that our validation and test splits were executed by the
**separate co-located workload** described in A12.3 — same host, same image, different process from
the one serving anonymous traffic — and MUST NOT present those measurements as though they came from
the public-facing process. Otherwise the reported scope of the measurement is wrong, which is the same
class of dishonesty the evidence requirements exist to prevent.

#### Acceptance additions (§14)

- [ ] **A-32** Confirm the public-serving container's filesystem does not contain the paid credential,
  and that the scored workload is not reachable over HTTP from outside the host (A12.2, A12.3).
- [ ] **A-33** Confirm the daily spend ceiling is enforced before provider calls, survives a restart,
  and is reported on the health endpoint; exhaustion produces `blocked / provider_quota` (A12.5).
- [ ] **A-34** Attempt to read and to delete an artifact whose recorded path resolves outside the
  artifact root: both are refused and logged (A12.7).

### Amendment 13 — The tiers must be real: declared runs, an experimental path that browses (2026-07-27)

Extends **S-1.3**, **S-1.4**, **S-1.5**, **S-11.4**, **A2.2**, **§10**. Written after a
direction review at M4 against the original assignment.

#### Why this exists

Three things drifted, and all three point the same way: **the product currently claims a shape it
does not have.**

1. `classify()` returns `T-EXPERIMENTAL` for every task that is not refused. **`T-DECLARED` is never
   assigned to anything.** Every OP-4…OP-7 run — the four promised records — therefore renders with
   the experimental banner telling the reader it is best-effort and *excluded from the reported
   success rate*. The system disowns its own promised surface, and S-1.3's headline rate has no
   numerator.
2. A task the keyword router does not recognise terminates as `unsupported / policy_refused`
   **before a browser is opened**. The experimental tier is a refusal label, not an execution path.
   S-1.4 requires a generic agent loop as the fallback, and A2.2 requires an abstention to name the
   step it stopped at and the last observed page state — neither is possible without browsing.
3. The frontend states that tasks outside the declared surface *are attempted*, and the support
   matrix still marks OP-4…OP-7 "not yet implemented". Both are now false. This is the one place
   where the documentation over-claims relative to the build, which is the wrong direction for the
   only surface the honesty requirements are graded on.

Amendment 2 answered "across different sites" with the experimental tier on the assumption that the
tier **actually attempts the task**. As built, breadth is answered by site count, and the count is
two.

#### Requirements

**A13.1 `T-DECLARED` MUST be assigned when a task maps to a promised record.** Tier assignment is a
real classification with all three outcomes reachable, decided before execution (S-1.3). The
experimental banner (S-1.5) MUST appear only on genuinely experimental runs, and declared runs MUST
be the ones counted in the headline success rate. A run's tier MUST be visible in the API response
and the UI, and MUST match what the run actually did.

**A13.2 The experimental tier MUST execute.** A public, policy-clean, read-only task that matches no
promised record MUST be attempted by the generic model-driven loop (S-1.4), not refused before
browsing. Specifically:

1. An entry point is resolved from the task (an explicit URL, or a site named in the task); if none
   can be resolved, *that* is the abstention reason and it MUST say so.
2. All §2 policy applies unchanged — robots (A10.1), egress (S-2.5), out-of-scope refusal (S-2.1).
   Policy refusals still happen before browsing; **"we do not have a script for this" is not a policy
   refusal** and MUST NOT be reported as `unsupported / policy_refused`.
3. A postcondition is still frozen before browsing and still owned by code. For an undeclared task
   it will be a weaker one — that a claim is bound to a located label, or that a named state
   transition was observed — but a weak postcondition that is checked is not the same as none, and
   a run that cannot verify its weak postcondition abstains rather than answering.
4. **Abstention MUST satisfy A2.2 with real observations**: the step it stopped at, the last
   observed page state, and why the postcondition could not be verified. Generic text is not an
   abstention; it is a refusal wearing one's clothes.
5. Experimental results remain excluded from the headline rate and visually distinct (S-1.5). Their
   value is that the attempt is real and the failure is inspectable.

**A13.3 User-facing copy MUST describe the build that is running.** The submit form, the support
matrix, the tier explanations, and every terminal explanation string MUST match current behaviour.
Two specific defects to clear: the claim that out-of-surface tasks are attempted (true only once
A13.2 ships) and the support matrix's "not yet implemented" on shipped records. **A string describing
the state of the build is a claim, and a stale claim is a false one** — build-state text MUST be
derived from what the system can do, or reviewed at every milestone gate.

**A13.4 The model-driven path is the default for real-site operations.** Requiring a magic phrase to
engage the planner means a reviewer submitting a promised task in plain English sees a scripted run
and never sees the mechanism that is being graded. The deterministic scripts remain — as the fallback
when the provider is unavailable, as the fixture demonstration path (which must not depend on a
provider), and as the comparison baseline — but they MUST NOT be what a natural-language task on a
real site gets by default. **The trace MUST record which path executed**, so the two are never
confused in reporting, and the analysis report MUST give success rates for each path separately.

**A13.5 The evaluation set MUST be executable by a harness, not only readable.** `eval/dev-set.md` is
prose today and nothing runs it. A harness MUST execute a split against the deployed system, compare
against each case's oracle, and emit per-case terminal status, failure class, evidence coverage, and
the provenance of S-10.7 (git SHA, pinned model ID, eval-set hash). The same harness runs the
held-out splits under A9.6 and A12.3. Without it there is no hard gate (§10.3), no first-run score,
and no source for the analysis report.

**A13.6 No milestone is assumed to be sacrificed.** S-13.1's cut order exists for a calendar that has
actually broken; it MUST NOT be used as a planning default. M5 (locator memory and the mutation gate)
and M6 (safety suite) are the evidence for self-maintenance and for the security claims, both named
in the assignment. M7 (the Task 2 seam) stays in scope, and **Task 2 itself is not assumed to be out
of scope** — nothing in Task 1 may be built in a way that presumes it will not be done.

#### Acceptance additions (§14)

- [ ] **A-35** Submit a promised-record task in plain natural language, with no special phrasing:
  the run is `T-DECLARED`, the model-driven path executes, and no experimental banner appears
  (A13.1, A13.4).
- [ ] **A-36** Submit a read-only task on a public site outside the promised set: a browser opens,
  the trace shows real steps, and the outcome is either a verified result marked experimental or an
  abstention naming the step, the observed state, and the unmet postcondition (A13.2).
- [ ] **A-37** Confirm no user-facing string misdescribes the build: support matrix statuses match
  what runs, and the submit form's description of tier behaviour is true (A13.3).
- [ ] **A-38** Run the dev split through the harness and reproduce its reported numbers, with
  provenance recorded (A13.5).

### Amendment 14 — Closing the gaps an independent review found against the assignment (2026-07-28)

Extends **A7.6**, **A6.3**, **§10**, **S-10.8**, **S-11.4**, **A12.2**, **§12**, **§14**. Written
after an independent reviewer read the assignment and the full spec with no other context and judged
a faithful implementation to land at a **strong B with an unsecured A**.

#### Measurement: two of the four named analysis dimensions had no source

The assignment names **runtime performance, cost, scalability, and correctness verification**. Cost
has A7.6 and A9.4; correctness has §4 and §10. The other two had only acceptance item A-25 demanding
numbers that no requirement produced.

**A14.1 Latency MUST be instrumented exactly as cost is.** Every run records **per-step and per-run
wall-clock duration** and **time to first result**, stored in the trace and shown in the UI, in the
same way A7.6 requires for tokens and USD. The analysis report gives the distribution over eval runs
(median and spread, not a single best case), broken down by declared vs experimental tier and by
model-driven vs deterministic path (A13.4).

**A14.2 Scalability MUST be measured, not asserted.** S-11.8 fixes concurrency 2 and queue depth 2
as a design constant; that is a decision, not a measurement. The report MUST carry at least:
throughput at full concurrency, the point at which the queue saturates and 429 begins, queue wait
time under load, and the measured cold-start duration (A8.5). One honest number each is enough; zero
is not.

**A14.3 The refusal rate on unseen tasks MUST be measured.** S-2.1's anti-bot refusal and A10.3's
fail-closed robots handling are both correct and both terminate before anything interesting happens.
Their **frequency** on undeclared-site tasks MUST be reported, so a policy-shaped outcome reads as a
characterised property rather than as a system that mostly says no.

#### Breadth needs a number, not a disclosure

**A14.4 An experimental-tier evaluation split MUST exist.** 8–10 public, policy-clean, read-only
tasks on sites that appear in **no** promised record, authored by the product owner (A8.15). It is
run through the A13.5 harness and reported as its own figure: **attempt rate, verified rate, and
abstention rate**, with an interval per S-10.13.

This split — not the declared site count — is the answer to the assignment's *"reliably executes them
across different sites"*. It raises A13.2's bar from *abstain honestly* to *attempt and answer*, and
it converts R-11 (*"it can read as 'doesn't work'"*) from a disclosed weakness into a measured
property. It does **not** enter the headline declared-tier rate (S-1.3 unchanged); it is reported
beside it. The graders' own unseen tasks land on this path, so it is the surface most likely to
decide how the system reads.

#### Evidence the graders can actually see

**A14.5 The held-out splits ARE published at submission.** This supersedes A6.3's "never committed".
The holdout exists to keep the engineering session honest (S-10.3, S-10.4), and that purpose ends the
moment the splits are scored — S-10.6 already reclassifies them as regression suites after the first
run. Committing them at submission, with `eval/holdout-manifest.md`'s **pre-committed hashes proving
the content predates the scored runs**, demonstrates the discipline *and* shows the work. Unchanged:
the engineering session never sees them before scoring, and the first run is still the reported score.

**A14.6 Self-maintenance MUST be demonstrated once on markup we do not control.** Every healing
demonstration today runs on the fixture — a site we wrote. Amendment 1 removed it from the promised
surface but left it as the sole *evidence* surface for one of the two mechanisms the assignment names
by name. At least one mutation case MUST therefore run against an **archived DOM of a real target
page**, mutated the same way (S-9.2's catalogue), with the same detection → cross-family
re-derivation → re-verification → write-back sequence. Archived, not live, so the case is
deterministic and re-runnable.

**A14.7 The gate-suite operations return to the frontend as mechanism evidence.** GS-1, GS-2 and GS-3
(A1.2) currently appear in no public surface at all, which means the strongest shortcut-proof and
mutation evidence in the system is invisible to a reader. They MUST be shown — in a section clearly
separated from the support matrix, carrying A1.3's wording that the fixture is **our own evaluation
environment, not a supported website**, and appearing in **no reliability or success-rate figure**.
Amendment 1 is **not** reversed: a reliability number measured on a site we control is not evidence,
and labelling does not make it one. What is being published is the *mechanism*, not a promise.

**A14.8 The known-limitations list has contents.** S-11.4 requires the list to exist; nothing defined
it. Each entry MUST carry: a **concrete task, phrased as a user would phrase it**, what the system
actually did, why, and the resulting `terminal_status` / `failure_class`. Entries MUST be
reproducible by a reader against the deployed system. Acceptance item **A-4's citation of `T1.9` is
replaced by this requirement** — `T1.9` is an ID in `docs/task1-discovery.md`, which the acceptance
reviewer does not read (§14), so as written it is unresolvable for its intended audience.

**A14.9 The shortcut-refusal penalty MUST be broken out in reporting.** S-4.4 scores a correct answer
that skipped a declared required action as `failed / required_action_skipped`. That is a
**self-imposed** penalty nothing in the assignment asks for, and it depresses our own measured rate.
It stays — it is what makes "substantive UI action" mean anything — but the analysis report MUST show
it as its own category, so deliberate strictness is not read as inability.

#### Credentials after scoring

**A14.10 Once our own splits are scored, the public path moves to the paid credential.** A12.2's
topology exists so that external traffic cannot consume the quota our evaluation depends on
(S-11.11). **That reason expires when the evaluation is complete.** After the test split's first run
(S-10.6), the public-serving deployment MUST be switched to the paid credential, bounded by A12.5's
enforced daily ceiling — which is what makes the switch safe. The switchover date MUST be recorded.

Two consequences, both improvements: grader traffic no longer exhausts a 500-request free daily limit
against ~294 requests per round (A9.6), and A7.9's disclosure strengthens — with all traffic on the
paid tier, **no content sent to the provider is used to improve its products**. Until the switchover,
A12.2 holds unchanged.

#### Keeping Task 2 buildable

Task 2 is not assumed to be out of scope (A13.6). Three decisions are cheap now and expensive later.

**A14.11 The run core is task-agnostic.** The run record, artifact store, evidence-bundle rendering,
and the `terminal_status` taxonomy MUST NOT be browser-specific. `failure_class` (S-5.3) is a closed
set of browser-shaped values; per-task extensions are added by amendment rather than by forking the
model. A Task 2 build reuses the run view, the evidence bundle, and the honesty machinery unchanged.

**A14.12 The eval harness is built around splits, oracles, and provenance — with a pluggable case
schema.** A13.5's harness MUST NOT be written to the browser-shaped dev-set schema. Task 2 needs the
same split discipline, first-run rule (S-10.6) and provenance (S-10.7) over different case fields.

**A14.13 Clarification of S-12.4.** "MUST NOT import internal modules" binds the **conformance test**
that proves the seam is consumable from the contract alone. It does **not** bind a Task 2 product,
which may reuse the store, the run model and the frontend. Read the other way it would force a
duplicate artifact store and UI for no benefit.

#### Submission surface

**A14.14 The README MUST cover what the assignment asks it to cover**: how to run, key design
decisions, and where AI helped — in addition to the honesty disclosures scattered across S-2.6,
S-2.12, S-3.7, S-4.3, A1.3, A4.2, A7.9, A9.9 and A12.4. The repository MUST be public, and the
submission states the repo URL and the frontend URL.

**A14.15 The prompt records need a reader's entry point.** `CLAUDE.md` requires verbatim logging of
everything, in order — that rule is unchanged and is what makes the records evidence rather than a
highlight reel. But the assignment asks for **key** prompts and says the graders will read them, so
`prompts/` MUST also carry a short index naming where the substantive decisions happen (file, and
what was decided), so a reader can find them without reading two long logs end to end.

#### Acceptance additions (§14)

- [ ] **A-39** The analysis report carries measured latency (distribution, split by tier and path),
  throughput, queue-saturation point, cold start, and the unseen-task refusal rate (A14.1–A14.3).
- [ ] **A-40** The experimental split has been run through the harness and its attempt / verified /
  abstention rates are reported with an interval (A14.4).
- [ ] **A-41** The held-out splits are in the repository, and their content hashes match the
  pre-committed values in `eval/holdout-manifest.md` (A14.5).
- [ ] **A-42** A healing demonstration exists against an archived real-page DOM, not only the
  fixture (A14.6).
- [ ] **A-43** The frontend shows GS-1/GS-2/GS-3 as mechanism evidence, clearly outside the support
  matrix and absent from every success-rate figure (A14.7).
- [ ] **A-44** The known-limitations list entries are concrete and reproducible against the deployed
  system (A14.8); shortcut refusals are reported as their own category (A14.9).
- [ ] **A-45** README covers how to run, design decisions, and where AI helped; `prompts/` carries an
  index; the repository is public (A14.14, A14.15).

### Amendment 15 — Free-first with fallback on the public path (2026-07-28)

**Supersedes A14.10.** Extends **A8.8**, **A12.5**, **A7.9**. Raised by the product owner against
A14.10 and accepted: A14.10 was over-specified.

**A15.1 After scoring, the public path runs free-first with automatic fallback to the paid
credential** — not paid-only as A14.10 required. The model is the same pinned ID either way (A9.2);
the tiers differ in quota and billing, **not in model or output quality**. Paid-only therefore
discards a free daily allowance for no gain.

The prohibition in A8.8 rested on two reasons and **both have since expired**: the quota wall
(S-11.11) protected an evaluation that is complete by then, and "nothing at runtime enforces the
spend ceiling" was answered by A12.5. A restriction whose reasons are gone is no longer a control; it
is a cost.

**A15.2 Fallback MUST trigger on rate-limit responses, not only on daily exhaustion.** The free tier
is RPM 15 (A9.6). Two concurrent runs during a grader burst can hit that ceiling **mid-run**, and a
run that fails as `blocked / provider_quota` for a limit the paid key would have absorbed is a
self-inflicted failure in front of the person grading it. Any provider quota or rate-limit signal —
daily exhaustion, RPM throttling, `RESOURCE_EXHAUSTED` — MUST fall through to the paid credential.
Genuine exhaustion of **both** tiers, or the A12.5 daily ceiling, remains `blocked / provider_quota`.

**A15.3 What still holds.** The A12.5 daily USD ceiling is what makes this safe and MUST be enforced
before every call regardless of tier; it is the only backstop once fallback is automatic. A8.9's
per-run record of which credential tier was used stays mandatory, and it is now load-bearing rather
than informational. The session cap (S-11.12) and queue depth (S-11.8) are unchanged.

**A15.4 Disclosure.** With fallback automatic, some public-demo traffic runs on the free tier, whose
content the provider uses to improve its products (A7.9). Page content is public by policy (P2), but
**the task text is written by whoever submitted it** — including a grader's unseen test wording. The
README MUST state this plainly rather than implying every request is on the paid tier.

**A15.5 Before the switchover, nothing changes.** Until the test split's first run is complete
(S-10.6), A12.2's topology and A8.8's prohibition hold exactly as written: no paid credential on the
public-serving container, no fallback on that path. The switchover date is still recorded (A14.10's
one surviving clause).

### Amendment 16 — The acquisition seam takes on the SEC identity semantics (2026-07-28)

Extends **§12** and **`docs/task2-seam.md`**, which moves to **v1.1**. Source: the product owner's
parallel proposal `Q1_Q2_SEC_FILING_CONTRACT.md` (v0.2). Its **semantics are adopted; its surface
area is not.**

**A16.1 Assessment.** The proposal is right about the things our seam got wrong, and those things are
all in the same family: **identity and time**. Our v1.0 identified a filing by `(cik,
accession_number)` and recorded exactly one timestamp. That is not sufficient to be correct. The
adopted items below are each a case where the current seam would produce a **confident wrong answer**
— the failure class this whole system is built against — not a case of missing convenience.

What is **not** adopted is the delivery surface: two acquisition profiles, an eleven-role taxonomy, a
Q1-emitted evidence/locator object, five transport endpoints with capability tokens and signed URLs,
and eighteen acceptance cases. That is a week of work whose absence costs the seam nothing, while M5,
M6 and M8 are outstanding. A16.9 records what was deferred so it is a decision rather than an
oversight.

#### Adopted

**A16.2 Three CIKs are three different things.** The first ten digits of an accession identify the
**submitting** CIK, which may be a filing agent; the archive path CIK is a third form; a filing may
disclose co-registrants. The seam MUST preserve `target_registrant_cik`,
`submitter_cik_from_accession`, and the archive CIK separately, reconcile them against SEC metadata,
and treat the **target registrant** as the filing's identity. Where an accession alone does not
resolve to exactly one registrant, the seam returns `needs_registrant_cik` — it does not assume the
prefix is the filer. Our v1.0 wording ("`cik` — the CIK of the filer") is wrong for
agent-submitted and multi-registrant filings.

**A16.3 Reproducibility needs an `as_of` cutoff and a revision policy.** "The FY2025 10-K" changes
meaning the day a `10-K/A` is accepted. A lookup MUST carry an `as_of` timestamp, and the seam MUST
NOT select a filing or amendment accepted after it. The revision policy is explicit
(`exact_accession` | `original` | `consolidated_as_of`). **An amendment is an overlay, never an
assumed replacement of the original filing.** This is the same discipline as postcondition freezing
(S-4.12): pin what the answer was computed against.

**A16.4 Four dates, none inferred from another.** `report_period_end` (fiscal period),
`filing_date`, `accepted_at` (SEC acceptance), and `retrieved_at` (our fetch) are separate fields. A
missing date MUST NOT be derived from a different one. Fiscal year is the year of the report period,
not of submission.

**A16.5 The resolution evidence is retained.** The SEC submissions JSON, the filing index, and the
archive directory index used to resolve the filing MUST be stored and hashed like any other
representation. Without them, "why this accession?" is unanswerable after the fact — which by our own
§4 standard means the resolution is unverified.

**A16.6 Raw and derived representations are distinct and raw is immutable.** A document may carry
several representations. Each has its own identity, hash, and `retrieved_at`; a derived one (e.g.
normalised text) MUST name the representation it came from and the transform's name and version, and
MUST NOT overwrite the raw bytes. If the same URL later serves different bytes, that is a **new
representation with a new hash** — the prior one stands. The URL is provenance, not identity.

**A16.7 Metadata visibility is not availability.** A filing can appear in SEC metadata before every
archive object is retrievable. Bounded retry is permitted; **a bundle MUST NOT become verified from
metadata alone** when a mandatory artifact is missing. It terminates as partial or failed.

**A16.8 Relationships come from SEC metadata only.** `amends` / `amended_by` / `related_filing` are
derivable from submissions metadata and are recorded. **`incorporates_by_reference` is NOT a Task 1
duty** — detecting it requires reading incorporation statements inside the filing, which is document
structure, which S-12.1 forbids on this side of the seam. The proposal assigns it to Q1; we reject
that. Task 2 determines incorporation and may record it against Task 1's stable document and
representation identifiers. What Task 1 guarantees is that Part III being absent from the primary
document is **representable without fabrication** — the inventory and relationships are complete
enough for Task 2 to say "incorporated" rather than "missing".

#### Rejected or deferred

**A16.9** Recorded so the boundary is a decision, not an omission:

- **2 requests/second is rejected.** S-2.15's ≤ 1 rps stands. It is already published as our stated
  posture and it is stricter; loosening a self-imposed limit for convenience is the wrong direction.
- **The capability-token authorisation model, signed content URLs, `401/403/410` semantics, and a
  7-day retention rule are deferred.** We have no authentication system, artifacts are already
  public run evidence, and retention is governed by A11.6 (age *and* disk-size bounds, with pinned
  demonstrations) — a second, conflicting retention rule in the seam would be a trap. Deferred to a
  future contract version if Task 2 needs private artifacts.
- **`q2_extended` is deferred.** Eagerly fetching every textual document in a submission and
  resolving related filings sits close to S-2.17's prohibition on enumeration and bulk download, and
  it buys nothing for a first Task 2 build. The mandatory two plus a complete inventory remain.
- **A Q1-emitted evidence/locator object is rejected.** Text offsets and DOM paths into a 10-K are
  Task 2's coordinate system. Task 1 guarantees **stable document and representation identifiers
  plus hashes**; Task 2 builds locators on top of them and must not alter Task 1's hashes.
- **The eighteen contract acceptance cases are reduced to the subset that exercises the newly
  adopted semantics** (agent-submitted accession, ambiguous company name, a filing with a related
  `10-K/A`, changed bytes at a stable URL, metadata visible before the archive object, plus the
  existing A-23/A-24 checks). The remainder are recorded in the seam document as future coverage.

**A16.10 New `failure_class` values** for the seam, added under the A14.11 extension mechanism
without touching `terminal_status`: `ambiguous_identity`, `filing_not_found_as_of`,
`identity_mismatch`, `hash_mismatch`, `pending_source_publication`.

**A16.11** `docs/task2-seam.md` moves to **v1.1** carrying A16.2–A16.8 and A16.10, with a changelog
naming what changed and what was deliberately deferred. `Q1_Q2_SEC_FILING_CONTRACT.md` is a proposal
input, not a second contract — the seam document remains the single normative one, and the repository
MUST NOT carry two documents that both look binding.

#### Acceptance additions (§14)

- [ ] **A-46** The independent consumer (S-12.4) resolves a filing whose submitting CIK differs from
  the target registrant, and the bundle records all three CIK forms without conflating them (A16.2).
- [ ] **A-47** A period lookup with an `as_of` before a known `10-K/A`'s acceptance returns the
  original filing and records the amendment relationship without substituting it (A16.3, A16.8).
- [ ] **A-48** The resolution snapshots are stored and hashed, and an ambiguous company name returns
  a candidate set rather than a choice (A16.5).

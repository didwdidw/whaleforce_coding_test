# M2 — Evidence, deterministic verification, and a status taxonomy that has been walked

**Date:** 2026-07-27 · **Gate (§13 M2): PASS**, on all four conditions:
deterministic re-resolution on saved artifacts works; label→value binding is enforced;
every `terminal_status` and every `failure_class` due by M2 has actually been produced; the
postcondition is frozen and hashed at plan time.

Still no model in the loop. Plans are scripted and only the fixture is reachable. What
changed is who decides the outcome.

---

## 1. The one structural change

At M1 the executor read a value off the live page and reported it. At M2 it may not decide
anything. Every plan freezes a postcondition **before it browses**, and the terminal status
comes from `app/verifier.py` re-extracting the answer from the stored artifact and comparing.

The executor is allowed to be wrong — it has been. What it is no longer allowed to do is
grade itself. `SUCCEEDED_VERIFIED` and `NO_RESULT_VERIFIED` appear in exactly one module.

Three properties carry the weight:

- **Re-extraction, not re-reading.** The verifier parses the stored DOM with lxml and
  resolves anchors independently of the executor's live query. The executor reads the
  product code by `#code`; the verifier finds the row whose header cell reads
  `Product code` and takes the adjacent cell. Different engine, different anchor, different
  moment.
- **The full artifact** (A7.4), never a reduced view. Verifying against the trimmed page a
  model was shown would make verification circular.
- **Label→value binding** (S-4.9). Shape checks are not verification: on a well-formed page,
  every wrong answer also looks like a product code.

## 2. The two M1 defects, replayed at the verifier layer

This is the question that mattered: given the artifacts those runs produced, does the
verifier reject them? `tests/test_verifier_replay.py`, 5 tests.

The artifacts are re-captures. Run storage is ephemeral, so the deploy that shipped the fix
destroyed the evidence of what it fixed (§5.2). They were taken through a real browser
against the same fixture, reproducing the same two behaviours.

**Defect A — an overlay task routed to the paginator.** Rejected twice over, and the second
one matters more than the first:

| Barrier | Result |
|---|---|
| `artifact_source_matches_plan` | Artifact captured on `/browse`; the plan froze `/gated` |
| Label anchor, with the URL check neutralised | `Product code` is not on that page at all |

**Defect B — a greedy regex searched for the sentence instead of the term.** This is the
dangerous one. The page really says `0 results`. The empty-state element really is there.
Both declared actions really happened. **Every check passes except one.**

The one that fires is the comparison between the term the page echoes back and the term
frozen at plan time: the plan committed to `lantern`, the artifact states it answered
`the fixture catalogue for lant`. `failed / verification_mismatch`, and specifically **not**
`no_result_verified`.

The suite includes the control that makes this mean something: fed the *same artifact* with
`the fixture catalogue for lant` as the frozen question, the verifier returns
`no_result_verified`. The rejection is the binding to the frozen question doing work, not a
verifier that refuses whatever it is shown.

And one test exists only to state the lesson as an assertion: step count, artifact count,
artifact state and step success are all still correct on the defective run. Anything that
inspects only those still sees nothing wrong.

## 3. The M2 gate: every status has been walked

M1's lesson was that the hard gate had not passed — it was *unreachable*. So every value in
both closed sets is declared with the milestone at which it becomes producible, and a ledger
records the first run that produced it. Writing the ledger is a side effect of terminating a
run, so it cannot drift from what the product did.

`test_every_status_due_by_m2_is_reached_by_running_the_product` drives them all into one
store and asserts nothing is overdue. `/coverage` shows the same table for the live
deployment.

| Status | How it is reached | Example |
|---|---|---|
| `succeeded_verified` | all required claims re-extracted and matched | search for `lantern` |
| `no_result_verified` | Mode A: empty-state element **and** the counter echoing the frozen term | search for `zzzznothing` |
| `no_result_verified` | Mode B: coverage anchor, full enumeration, predicate re-checked | "is any product priced over £100?" — pager says 14 items, 14 enumerated, none matches |
| `partial` | one claim verified, another's label moved | seed `mu2-text` renames `Product code` |
| `failed` | mismatch, unmet postcondition, skipped action, budget, defect | see below |
| `blocked` | policy, robots, site, queue, session quota | "show me the ground truth answer key" |
| `unverified` | a candidate with no deterministic confirmation | absence with no declared proof mode |

Five failure classes are **not** due until later and are marked so rather than quietly
missing: `provider_quota`, `provider_error`, `token_budget_exhausted`,
`context_budget_exceeded` (M3 — nothing calls a model yet) and `injection_detected` (M6).

Two honest notes on the ledger:

- `site_unavailable` is recorded with origin `test`, not `run`. Every natural way to make a
  page unreachable also makes its `robots.txt` unreachable, which is refused earlier as
  `robots_disallowed`. It is exercised with an injected navigation error, and the ledger
  labels it rather than blending it in.
- The live `/coverage` table starts long and shortens as outcomes occur, and a redeploy
  resets it (§5.2). The milestone gate is the suite's assertion, not the page's.

## 4. Two defects the new tests found in existing code

Both were found by writing the test first and watching it fail for the wrong reason.

**A postcondition with no claims reported success.** `_decide` treated "no required claims
failed" as "everything passed", so a plan that declared nothing to check returned
`succeeded_verified`. Absence of a failure is not a success. A claim-free postcondition now
terminates as `failed / postcondition_unmet` — the fix first made it `unverified`, which
Amendment 11 then tightened, along with three further instances of the same class (§6.2).

**`enforce_retention(retention_days=0)` silently meant 14 days.** `retention_days or
settings.artifact_retention_days` — an explicit zero is falsy. The caller asking to expire
everything got the default instead. Now an `is None` check.

## 5. What is deliberately conservative, and what is still open

### 5.1 A moved label costs a claim

Under `mu2-text` the reference code is still on the page and the executor still reads it
correctly by id. The run is `partial` anyway, because the binding its claim depends on
cannot be made. That is a false negative by construction and the right direction to err:
S-4.9 exists because a value that only *looks* right is the failure mode being defended
against. Re-anchoring across strategy families is a recovery behaviour and arrives at M3.

### 5.2 Evidence not surviving a deploy — raised here, decided as Amendment 11

`DATA_DIR` was `/tmp/task1-data` with no volume mounted, so every restart destroyed all runs
and artifacts. At M1 this was invisible. It stopped being invisible at M2: an evidence bundle
is the product's central claim, and a bundle whose artifact vanished on the next deploy is a
dangling reference that looks fine until someone opens it.

Decided by the product owner as **Amendment 11** — §6 is what was built. The accepted cost is
stated rather than hidden: a volume-mounted Zeabur service switches from `RollingUpdate` to
`Recreate`, so every deploy now takes a full cold start of downtime (~8 s, M1 report §4.1)
instead of the overlapping rollout. **Persistence is not free**, and that sentence belongs in
the analysis report, not only here.

### 5.3 The shortcut case, and what it does not prove

`Read page 2 without clicking next` reads the hidden rows straight from the DOM. The SKUs it
returns are **correct**, and it is scored `failed / required_action_skipped`, because the
capability being claimed is the interaction. This is S-4.4 working — and it is also the
honest limit of S-4.3: what is verified is *the case declared this action as required and
the trace shows it happened*, never *the action was impossible to bypass*.

### 5.4 What a verified claim still does not rule out

The value is bound to its label and re-extracted from preserved bytes. It can still be the
right shape from the wrong row on a page with two similar tables, or the right label in the
wrong period. Label binding narrows this; it does not close it. The decoy mutations (MU-4)
are where that gets measured, at M5.

## 6. Amendment 11, implemented

| ID | Requirement | Where |
|---|---|---|
| A11.1 | Volume for artifacts and the run database | `DATA_DIR` defaults to `/data/task1`; the image no longer sets it, so `app/config.py` is the single source |
| A11.2 | The `Recreate` cost is stated, not hidden | §5.2 here, and the deploy runbook |
| A11.3 | Homepage demonstrations pinned, exempt from every sweep, and dated | `artifacts.pinned`; the homepage shows each demo's capture date |
| A11.4 | Expiry renders as "expired on `<date>`" with metadata intact, in HTML **and** API | run detail re-resolves artifact state at render time; `/api/artifacts` answers 410 with the full record |
| A11.5 | Health verifies the store by writing to it, never falls back silently | write probe **and** a mount check; unhealthy → HTTP 503 |
| A11.6 | Age limit and size ceiling, oldest-first over unpinned, every eviction recorded | `retention_events` table, warning at 80% of the ceiling |
| A11.7 | Vacuous verification fails closed | `Verifier._vacuous`, plus the coverage gate and the fixture self-test |
| A11.8 | Explicit falsy ≠ unset | `_resolve` in `app/config.py`, with provenance on `/healthz` |

### 6.0 Verified on the deployed system

| Check | Result |
|---|---|
| Volume | 10 GiB PVC bound, mounted at `/data`; `persistent: true`, `on_mounted_volume: true`, `mount_required: true` |
| Rollout strategy | flipped to **`Recreate`**, exactly as A11.2 predicted |
| **A-29** | A user run and its artifact created *before* the container was replaced both still resolve after it: `succeeded_verified`, artifact `stored`, HTTP 200. All five pre-executed demonstrations survived with their artifacts pinned |
| **A-30** | Forced expiry in production: API answers **410** with `state: expired`, `expired_on`, and `source_url` / `retrieved_on` / `sha256` / `length` all intact; the run page shows "expired on 2026-07-27 … hash retained". A pinned demonstration in the same sweep stayed at HTTP 200 |
| **A-31a** | In the production image, `DATA_DIR=/dev/null/nope` → refuses to start; `DATA_DIR=/tmp/ephemeral-demo` (writable, not a mount) → **also refuses**, naming the silent-fallback condition |
| **A-31b** | `/healthz` reports the ceiling fraction, the pinned count, and the eviction that just happened (`reason: age, artifacts: 2, bytes: 6660`) |

**The measured cost of `Recreate`: a 1.05 s visible outage**, on two samples — one pod
replacement and one true `rollout restart`. That is *shorter* than expected, and the reason
matters more than the number: the terminating pod kept answering for ~9 s while the
replacement booted in ~4.8 s, so the two overlapped. There is still no readiness probe, so
this remains a race rather than a guarantee, and the honest upper bound is the app's
boot-to-serve time of ~5 s if the old pod's endpoint is withdrawn first.

One correction to the recommendation made at M1: a health check on `/healthz` no longer buys
zero-downtime deploys, because `Recreate` never overlaps two ready pods by design. It is
still worth setting — it stops traffic reaching a pod that is up but not yet serving — but
the payoff is smaller than it was before the volume.

### 6.1 The check a write probe cannot make

A11.5 asks for a write probe rather than a path-existence check. Implementing it exposed
that a write probe is **also** insufficient here: the image runs `mkdir -p /data`, so with no
volume attached the directory exists, is writable, and passes. Everything works and every
artifact dies at the next deploy — the precise condition the volume was mounted to prevent.

So the store also compares the data directory's device id against `/`. A mounted volume has
its own; a directory the image created does not. That is the check that catches "the volume
was never attached", and it is off only in development, where the data directory is an
ordinary folder.

### 6.2 Where the two promoted rules changed behaviour beyond their original bug

**A11.7** turned out to have three more instances than the one that prompted it:

- a claim set that is entirely **optional** — an empty claim set wearing a hat, since the run
  could pass with no value confirmed;
- **zero anchors resolved**, which previously returned `unverified`. It is now `failed`:
  nothing was examined, so nothing was verified. `unverified` is kept for the narrower case
  where an anchor *did* resolve and the claim still could not be established — absence
  without a declared proof mode. That reading is what keeps A11.7 and S-5.1 consistent;
- the **coverage ledger's own gate**, which passed on an empty ledger because nothing was
  overdue either, and the **fixture's self-test**, which compares ground truth across
  mutation seeds and would have passed with zero seeds or an empty baseline.

**A11.8** produced one behaviour change worth naming: an environment variable that is set but
unreadable — `BUDGET_MAX_STEPS=lots`, `ALLOW_PRIVATE_EGRESS=maybe` — now stops the process
instead of quietly resolving to the default. Guessing `False` for an unrecognised flag is the
same failure as treating `0` as unset: an operator who set something believed it did
something.

## 7. What M3 inherits

- The postcondition is the interface. The planner may propose actions, locators and
  candidate claims; it may not write the postcondition or reach `verified` (S-4.7).
- Recovery re-verifies against the **identical frozen object** (S-7.4). The hash check is
  already in the verifier's first position, so a recovery that lowered the bar fails there
  rather than being argued about.
- Four failure classes become reachable the moment a model is called. They are declared as
  due at M3, so the coverage gate will fail until they have been produced.
- Abstain-don't-guess now holds at three levels — no search term, ambiguous routing, no
  threshold for a predicate. A planner is a fourth, and the same rule applies: an answer to
  a question that may not have been asked is worse than no answer.

---

**Tests:** 107 passing (93 without a browser, 14 integration).
**CI:** two jobs — policy and semantics on every push, plus a browser job running the replay
suite and the M2 gate.

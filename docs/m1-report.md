# M1 — Walking Skeleton: deployed, checked, and what it cost to find out

**Date:** 2026-07-27 · **Deployment:** `https://wf-agent.zeabur.app` (app),
`https://wf-fixture.zeabur.app` (fixture) · **Host:** Tencent / Ashburn, ZeaburOS + k3s (A9.10)

**Gate (§13 M1): PASS.** A public URL accepts a task, runs against the fixture with no model in
the loop, shows progress and a step trace, and the queue and 429 behaviour are correct.
**A8.5 cold start is still owed** — the one measurement that needs a container start (§4).

---

## 1. Post-deploy checks

| Check | Result |
|---|---|
| Both services serving their own role | `wf-fixture` = FIXTURE (14 items, 10 seeds), `wf-agent` = APP |
| Fixture `GET /search` | **405** — GS-1 stays shortcut-proof |
| Fixture `POST /search` | 200 |
| Fixture ground-truth self-test | `ok: true` — mutations cannot move an answer (S-9.3) |
| Build provenance | `git_sha` resolves to the deployed commit |
| Queue saturation, 8 back-to-back | 4×`202`, 4×`429` |
| 429 payload | `blocked / queue_full`, `Retry-After: 60`, `counts_as_success: false` |
| Out-of-scope task | `T-REFUSED` → `unsupported / policy_refused`, no navigation |
| **A-28** guard state on `/healthz` and in a run's first trace step | Both report `ssrf_guard_enabled: true`, **including on a run the guard itself refused** |
| Warm homepage latency | ~0.84 s total, ~0.63 s TTFB (5 samples) |

Every run that produced a value ended `unverified`, `counts_as_success: false`. That is the
correct M1 outcome and it doubles as a live check that `unverified` never renders or
aggregates as success (S-5.2).

## 2. Was any wrong answer ever counted as success? No — and structurally it could not be

A run searched for a mangled term and reported **"0 results"**. The question that matters is
what status it terminated in, because "I looked and didn't find it" presented as success
would be a verified-but-wrong claim, and Gate 1 of §10.3 requires zero of those.

**It terminated `unverified`, `counts_as_success: false`.** Not `no_result_verified`.

This was not luck. `app/executor.py` contains **zero** references to `SUCCEEDED_VERIFIED` or
`NO_RESULT_VERIFIED`: the M1 executor has no code path that can reach a success status at
all, by construction. Amendment 3's rule — absence without a coverage anchor is `unverified`,
never `no_result_verified` — cannot be violated here because the anchor machinery that would
be required to claim absence does not exist yet.

Worth stating plainly for the record: **the hard gate was not exercised, it was unreachable.**
It becomes a live constraint at M2, when the verifier gains the ability to mark something
verified. The check to carry forward is that a proof-of-absence path must demand its coverage
anchor before it can reach `no_result_verified`.

## 3. Two defects that shipped, and the reason they shipped

Both reached the deployed system. Neither raised an error. Both returned something that read
like an answer.

**Routing matched a bare `page`.** "Dismiss the overlay on the **gated page** and read the
reference code" routed to the paginator and returned `Page 2 of 3 · 14 products` — a correct
pager reading, for a question nobody asked.

**Search-term extraction was greedy.** "Search the fixture catalogue for lantern" produced the
term `"the fixture catalogue for lant"`, which returned **0 results** and reported that as the
finding.

### 3.1 The method failure was larger than either bug

They were found by reading the candidate value of every deployed run. They were **not** found
by the checks run before deploying, and those checks had passed — because they verified
*structure*: step counts, artifact counts, terminal statuses, HTTP codes. Every one of those
was correct in both defective runs. The overlay run produced 8 steps and 2 artifacts and
terminated cleanly; it simply answered a different question.

**Verifying structure while assuming content is precisely the failure mode this product
exists to prevent.** It is the same shape as the traps the spec names: the second sortable
table, the identical adjacent prices, the numeric-versus-lexicographic sort. In each, the
machinery runs correctly and the answer is wrong, and nothing in the execution reports a
problem.

This is why the M2 deterministic verifier is the core of the product rather than a
finishing step. A verifier that re-resolves a stored anchor inside the full preserved
artifact and re-extracts the value independently is the only thing that closes this gap —
because it checks *what the answer is*, not *that a run happened*. Until it exists, no
number this system produces should be believed, which is exactly why M1 terminates
everything as `unverified`.

The correction has been generalised rather than patched twice:

- **Abstain instead of guessing, at every level.** A task naming no search term abstains
  rather than inventing one. A task matching more than one operation returns `unsupported`
  naming the candidates, rather than taking the first — the "gated page" mis-route was not a
  weak marker, it was the act of choosing under ambiguity.
- **14 regression tests** pin the routing and the extraction, including the exact inputs that
  failed.

## 4. Still owed

**A8.5 cold start.** It needs a container start, and the service has been warm since the last
deploy. It will be measured on the first request after the next restart — the figure a grader
actually experiences, not the warm 0.84 s above.

## 5. Amendment 10, implemented

| ID | What it required | Where |
|---|---|---|
| A10.1 | RFC 9309 matching: longest match, Allow wins ties, `*`/`$`, groups end only at a `User-agent` line | `app/robots.py` |
| A10.2 | `urllib.robotparser` banned | enforced by parsing imports, not grepping text |
| A10.3 | 404 = no restrictions; unfetchable/5xx/unparseable = refuse | `RobotsCache.decide`, with the boundary tested both ways |
| A10.4 | Every decision cites directive, pattern and group user-agent, or states "no rule matched" | `RobotsDecision`, recorded in the trace for allows and refusals alike |
| A10.5 | Applies to every origin including the seam's fetcher | `app/fetcher.py` uses the same components |
| A10.6 | Dedicated semantics tests, live SEC body as a fixture | `tests/test_robots_semantics.py`, `tests/fixtures/` |
| A10.7–A10.9 | Production default, refuse to start, guard state recorded | already built at M1; now spec-backed |
| A-27 | Semantics tests run in CI, not by hand | `.github/workflows/tests.yml` |

The A10.3 boundary is the one worth re-reading. `books.toscrape.com` serves **no**
`robots.txt`, and a fail-closed rule that treated 404 as "could not fetch" would have refused
that origin entirely and silently removed OP-6 and OP-7 from the promised surface. The
distinction is between *the policy says nothing* and *we could not read the policy*; only the
second is a reason to refuse.

CI additionally asserts that the vendored SEC fixture still places `Disallow: /cgi-bin` and
`Allow: /Archives/edgar/data` after a blank line inside the `User-agent: *` group. Without
that check the fixture could drift into a shape that no longer exercises A10.1.4, and the
tests would keep passing while testing nothing.

## 6. What M2 inherits

- The verifier is the answer to §3.1, not an incremental feature.
- `no_result_verified` must be unreachable without a coverage anchor (Amendment 3), and the
  first code that can reach a success status is the first code that can violate Gate 1.
- Verification re-resolves anchors in the **full stored artifact** (A7.4). The artifacts are
  already captured and hashed; expiry is a recorded state, so a bundle is never a dangling
  reference.
- The postcondition is frozen and hashed at plan time (S-4.12). Nothing freezes one yet — the
  run detail page says so rather than showing an empty panel.

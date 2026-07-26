# M0 — Preflight Report

**Session:** Engineering Session · **Date:** 2026-07-26 · **Spec:** `docs/task1-spec.md` §13 M0, A7.8, A8.3, A8.5

**Verdict: M0 is PARTIALLY COMPLETE. Five of six items pass. Only M0.1 (RAM) and the A8.5
cold-start figure remain, both of which must be measured inside the deployment image. One spec
assumption was contradicted by reality and is resolved by Amendment 9, approved.**

| M0 item | Gate | Status |
|---|---|---|
| M0.1 RAM headroom, browser + 2 contexts + app under load | 13(a) | **Outstanding** — local baseline 794 MiB; to be measured on the production host |
| M0.2 Reachability from the deployment IP | 13(b) | **Pass** — all clear from `43.166.128.37`; every target 200, both expected non-200s correct |
| M0.3 §3.4 policy facts re-verified | 13(c) | **Pass** — all facts hold verbatim; one correction, one new hard requirement (both now A9.8/A9.9) |
| M0.4 Account's actual Gemini rate limits | 13(d) | **Pass** — RPM 15 / TPM 250,000 / RPD 500, read from AI Studio |
| M0.5 Token + USD per run, requests/day feasibility | A7.8 | **Pass** — measured; arithmetic closed in §6 |
| M0.6 OP-4…OP-7 targets pinned, OP-5 variant chosen | 13(e) | **Pass** — all eight targets verified; OP-5 primary variant kept |
| A8.5 Host choice + cold-start duration | A8.5, A9.10 | **Host decided** (Tencent/Zeabur); cold start rides on M0.1 |

**The one thing that contradicts the spec:** the model family Amendment 7.10 is written around no
longer exists for this account. `gemini-2.5-flash` and `gemini-2.5-flash-lite` both return
`404 NOT_FOUND — "no longer available to new users"`. See §5. **Resolved: Amendment 9 is approved**
(spec §16), with additions by the product owner — §9 records what it obliges us to build.

---

## 1. M0.1 — RAM headroom

**Not yet measured on a cloud tier.** A8.3 requires this from a real container, and the reason is
sound: measuring from a residential machine is always green. What follows is the *local baseline*,
taken to size the box worth testing — not the gate.

Measured on macOS 14.5 / arm64 / 16 GiB, one Chromium process, two contexts, both loading
concurrently (`preflight/measure_ram.py`, result in `preflight/results/ram-local-macos.json`):

| Mark | RSS |
|---|---|
| Python app baseline | 31.0 MiB |
| + browser launched | 316.7 MiB |
| + 2 contexts idle | 482.0 MiB |
| + both pages loaded concurrently (S&P 500 + a books.toscrape category) | 757.1 MiB |
| + full DOM serialised in both contexts (artifact capture) | 762.3 MiB |
| + screenshot in both contexts | 781.8 MiB |
| **Peak sampled** | **794.0 MiB** |

Peak by process: `chrome-headless-shell` 601.4 MiB, `node` 155.5 MiB, `Python` 35.3 MiB.

Two things this already settles:

- **512 MB tiers are out.** Render's free tier and Fly's 256/512 MB machines cannot hold this. The
  measurement box must be 1–2 GB.
- **The Playwright Node driver costs 155 MiB** and is easy to forget. Playwright's Python binding
  spawns a Node process; that is permanent overhead in production, not a measurement artifact.

Concurrent load of both pages took 1.54 s on a residential connection, and full-page DOM was
1,933,703 chars (S&P 500) against 52,426 chars (category listing) — a 37× spread that the artifact
store has to absorb.

**What is needed to close this gate:** `preflight/run_cloud_preflight.sh` run on a 1–2 GB Linux
container on a datacenter IP. It prints cgroup limits, does M0.2, times cold start, and runs the RAM
measurement.

## 2. M0.2 — Reachability — **PASS**

Measured from the production host `43.166.128.37` (Tencent Cloud, Ashburn US) on 2026-07-26T15:07:40Z.
Verbatim session record: `server_environment.txt`. Summariser exit status **0 — ALL CLEAR**.

| Target | HTTP | Resolved | Bytes | Seconds |
|---|---|---|---|---|
| `control_example_com` (TLS control) | **200** | 104.20.23.154 | 559 | 0.046 |
| `en.wikipedia.org/wiki/List_of_S%26P_500_companies` | **200** | 208.80.154.224 | 1,509,745 | 0.050 |
| `en.wikipedia.org/robots.txt` | **200** | 208.80.154.224 | 28,275 | 0.040 |
| `books.toscrape.com/` | **200** | 35.211.122.109 | 51,294 | 0.098 |
| `books.toscrape.com/robots.txt` | **404** (expected) | 35.211.122.109 | — | 0.075 |
| `books.toscrape.com/.../nonfiction_13/` | **200** | 35.211.122.109 | 52,725 | 0.097 |
| `www.sec.gov/robots.txt` | **200** | 104.68.246.135 | 2,622 | 0.071 |
| `www.sec.gov/Archives/edgar/data/320193/` | **200** | 104.68.246.135 | 451,854 | 0.051 |
| `data.sec.gov/submissions/CIK0000320193.json` | **200** | 23.49.181.96 | 164,394 | 0.055 |
| `www.sec.gov/robots.txt` **without declared UA** | **403** (expected) | 104.68.246.135 | — | 0.090 |

**No site treats this IP differently from a residential one.** The risk the product owner flagged —
that a Tencent netblock might be refused — did not materialise on any of the three sites. The TLS
control returned 200 first, so none of the results are an artefact of a missing CA bundle.

Three things the measurement settled beyond the gate itself:

**The host is genuinely in the US.** Cloudflare's trace reports `colo=IAD`, `loc=US`, and Wikipedia
resolved to `208.80.154.224` (Wikimedia's US edge) rather than the Singapore address a residential
Taiwan run gets. The Ashburn region is behaving as an Ashburn region.

**Latency is 5–10× better than the residential control**, which changes what the wall-clock budget
buys. Wikipedia 0.472 s → **0.050 s**, books.toscrape 1.066 s → **0.098 s**, SEC 0.322 s → **0.051 s**.
The S-6.1 default of 180 s wall clock was sized without this; page fetch is now a small fraction of a
run, and the budget is dominated by browser work and model latency rather than by the network.

**A9.8 reconfirmed on the production IP.** SEC returned **403** to the undeclared User-Agent — and
notably the 403 body arrives gzipped, so a naive error path that tries to read it as text gets
mojibake rather than a diagnosis. The fetcher's error handling has to decompress before it reports.

### Correction: the OS is 24.04, not 22.04

The Zeabur dashboard reported Ubuntu 22.04; the box is **Ubuntu 24.04.4 LTS (noble), Python 3.12.3,
OpenSSL 3.0.13, kernel 6.8.0-124, x86_64**. The dashboard was wrong, and Step 2 of the runbook existed
precisely so this was checked rather than assumed. It resolves in our favour — nothing has to be
back-ported to Python 3.10 — but the lesson holds for the deployment image: the base image tag pins
the runtime, and the dashboard is not a source of truth.

### Host resource baseline, from the same session

| Measure | Value |
|---|---|
| CPU | 2 cores |
| Memory total | 3,723 MB |
| Memory used at idle (k3s + Zeabur agent) | **477 MB** |
| Memory available at idle | 3,246 MB |
| **Swap** | **1,987 MB, enabled** |
| Disk | 59 GB total, 5.2 GB used, 52 GB available |

The idle 477 MB corroborates the ~484 MB orchestration baseline the product owner quoted. Headroom for
the app is therefore ~3.2 GB against a measured 794 MiB peak — comfortable.

**Swap changes what the RAM gate means.** With ~2 GB of swap the box will not OOM at the peak, it will
get slow instead, and a slow run inside a 180 s wall clock fails as `timeout` — a symptom two steps
removed from its cause. So M0.1 must report **whether swap was touched at all**, not only the peak RSS.
A green peak on a swapping box is not a pass.

## 3. M0.3 — §3.4 policy facts re-verified — **PASS**

All fetched fresh today. Full copies in the scratch record; assertions automated in
`preflight/check_reachability.py`.

| Fact | Result |
|---|---|
| `en.wikipedia.org` robots `User-agent: *` block contains `Disallow: /w/`, `Disallow: /api/`, `Disallow: /wiki/Special:` | **Confirmed** (lines 148–161) |
| Article paths `/wiki/<Title>` are not Disallowed | **Confirmed** — only `Special:`/`Spezial:`/`Spesial:` variants and specific dewiki project pages |
| `books.toscrape.com/robots.txt` | **Confirmed 404**, nginx/1.21.6 |
| `www.sec.gov` robots: `Allow: /Archives/edgar/data`, `Disallow: /cgi-bin`, `Disallow: /search/` | **Confirmed** (lines 76, 80, 55) |
| SEC "Current max request rate: 10 requests/second" | **Confirmed verbatim** |
| SEC "The SEC does not allow botnets or automated tools to crawl the site" | **Confirmed verbatim** |
| SEC requires a declared UA with contact + `Accept-Encoding: gzip, deflate` | **Confirmed verbatim**, and enforced with 403 (§2) |
| `arxiv.org` robots: `Crawl-delay: 15`, `Disallow: /search`, `/find`, `/form`, `/api`; "Indiscriminate automated downloads from this site are not permitted" | **Confirmed** — exclusion stands |

**One correction to a §3.4 implication.** Wikipedia's `robots.txt` does contain `Crawl-delay: 5`, but
it sits inside the `User-agent: SemrushBot` block, not the `User-agent: *` block. **No crawl-delay
applies to us on Wikipedia.** Per-origin pacing is still enforced (S-2.15); it is our own choice, not
a robots directive, and the README should not claim otherwise.

## 4. M0.6 — Pinned targets — **PASS**

All eight aliases in `eval/dev-set.md` verified against the live pages
(`preflight/pin_targets.py`, `preflight/probe_sortable.py`, `preflight/probe_collapsible.py`).

| Alias | URL | Verified today |
|---|---|---|
| `WIKI_SP500` | `en.wikipedia.org/wiki/List_of_S%26P_500_companies` | 2 sortable wikitables: `#constituents` (504 rows, headers Symbol/Security/GICS Sector/GICS Sub-Industry/Headquarters Location/Date added/CIK/Founded) and `#changes` (408 rows) |
| `WIKI_GDP` | `en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)` | 2 sortable wikitables (spec said 3): `Country/Territory` + IMF 2026 / World Bank 2025 / UN 2024, and a `Regional groupings` table |
| `WIKI_APPLE` | `en.wikipedia.org/wiki/Apple_Inc.` | 23 `mw-collapsible`; 3 carry `mw-collapsed` in the served HTML, **all 23 collapsed after JS** (§6) |
| `BT_HOME` | `books.toscrape.com/` | 50 sidebar categories, "1000 results - showing 1 to 20.", "Page 1 of 50" |
| `BT_NONFIC` | `.../nonfiction_13/index.html` | **"110 results - showing 1 to 20."**, **"Page 1 of 6"** |
| `BT_FICTION` | `.../fiction_10/index.html` | **"65 results - showing 1 to 20."**, **"Page 1 of 4"** |
| `BT_POETRY` | `.../poetry_23/index.html` | **"19 results."**, no pager, 19 items, prices £14.19–£57.31 |
| `BT_ATTIC` | `.../a-light-in-the-attic_1000/index.html` | UPC `a897fe39b1053632`, Availability `In stock (22 available)` |

Every dev-set claim held except one: `WIKI_GDP` has **2** sortable wikitables, not 3. The dev case
(DEV-03) is unaffected — it anchors on the header `Country/Territory`, which the regional table does
not carry (`Regional groupings`), so the disambiguation the case relies on is intact.

**OP-5 variant: the primary collapsible variant is kept, not the S-3.4 lightbox fallback.** The
collapsed target is stable (identical set and order across two loads) and the state transition is
cleanly observable: the toggle is a `<button>` whose text flips `show` → `hide` and whose
`aria-expanded` flips `false` → `true`, with the URL unchanged.

One point in the spec's favour is stronger than Amendment 4.2 assumed. A4.2 says the collapsed content
is "generally present in the DOM before expansion", so an agent could read it without expanding.
Measured: while collapsed, `innerText` of those containers is **0–37 chars** — the content is in the
DOM (`textContent`) but not rendered, so it is absent from rendered text and from the accessibility
tree. An accessibility-driven agent (S-11.17, which is our architecture) genuinely cannot read it
without expanding. A4.2's honest qualification should stay in the README as written, because a
DOM-scraping agent *could* bypass it — but our reduced view cannot, and that is worth stating.

## 5. M0.4 — Gemini rate limits — **PASS**, and a model-availability failure

**Free-tier limits for `gemini-3.1-flash-lite`, read from AI Studio by the product owner
(S-11.18):**

| Limit | Value | Consumed at time of reading |
|---|---|---|
| Requests per minute | **15** | 13 |
| Tokens per minute | **250,000** | 28,610 |
| Requests per day | **500** | 23 |

Two separate constraints fall out of this, and they are not the same constraint.

**RPD 500 decides the credential policy.** Against ~294 requests per full round (§6), `500 / 294` is
**one round per day**, leaving ~200 requests for development iteration — and a round in which runs
actually spend the S-6.1 12-call budget is ~756 requests, which does not fit at all. Scored runs
therefore go on the paid key unconditionally (A9.6) and development keeps the free key with automatic
fallback (A8.8).

**RPM 15 is a scheduling requirement, not a quota to be discovered at runtime.** With concurrency 2
(S-11.8) and up to 12 calls per run, two runs stepping in parallel can exceed 15 requests/minute
without either run misbehaving. The scheduler MUST pace provider calls to stay under the limit
**proactively** — waiting for the provider to return 429 makes quota exhaustion a run outcome instead
of a scheduling decision.

**This is a distinct mechanism from S-11.8's HTTP 429**, and the two must not be conflated in the
code or in the UI:

| | S-11.8 HTTP 429 | Provider rate limit |
|---|---|---|
| Who is refused | the *user* submitting a task | *us* calling the model |
| Cause | our queue is full (depth 2) | our own call pacing |
| Surfaced as | HTTP 429 + `Retry-After`, `blocked / queue_full` | never, if paced correctly; `blocked / provider_quota` if genuinely exhausted |
| Correct handling | refuse fast, tell the user to retry | delay our own call inside the run's wall clock |

A provider 429 leaking out as a user-facing 429 would tell a grader the queue is full when it is not.

**Model availability, measured against the free-tier key** (`models.list()` plus a real
`generateContent` call each — listing alone is not proof, which is how this was found):

| Model | Stable | Input $/1M | Output $/1M | Callable on this key |
|---|---|---|---|---|
| `gemini-2.5-flash` | GA | 0.30 | 2.50 | **404 — no longer available to new users** |
| `gemini-2.5-flash-lite` | GA | 0.10 | 0.40 | **404 — no longer available to new users** |
| `gemini-3.1-flash-lite` | GA | **0.25** | **1.50** | **Yes** |
| `gemini-3.5-flash-lite` | GA | 0.30 | 2.50 | Yes |
| `gemini-3.6-flash` | GA | 1.50 | 7.50 | Yes |
| `gemini-3.5-flash` | GA | 1.50 | 9.00 | Yes |
| `gemini-3-flash-preview` | **preview** | 0.50 | 3.00 | Excluded by S-11.15 |
| `gemini-2.0-flash`, `gemini-2.0-flash-lite` | deprecated, shut down 2026-06-01 | — | — | Excluded |

Both 2.5 models appear in `models.list()` and fail on use. Any startup check that only lists models
would pass and then fail at the first real call, so **S-11.15's startup validation must issue a
minimal live call, not just a list lookup.**

Prices above were re-fetched from `ai.google.dev/gemini-api/docs/pricing` today, as A7.10 requires.
**A7.10's two quoted price pairs are still exactly right** (`gemini-2.5-flash` 0.30/2.50,
`gemini-3.5-flash` 1.50/9.00) — the prices did not move; the models became unavailable.

**Pinned model, approved by the product owner and now spec text (A9.2): `gemini-3.1-flash-lite`** —
the cheapest callable stable model. Three constraints attach to it:

- **A9.2.1 — no validation or test run before the pin is final.** Held-out splits score on their
  first run (S-10.6) and record the model ID (S-10.7); running one against a provisional model spends
  a run whose only value was that it could be spent once.
- **A9.5 — A8.11's comparison must include a non-lite candidate, and price is not a deciding
  variable.** At ~$0.15 per round, a 6× more expensive model costs ~$0.90 — inside the USD 5 ceiling.
  The pin is decided on locator-reasoning quality. The non-lite candidate is **`gemini-3.6-flash`**
  ($1.50 in / $7.50 out), not `gemini-3.5-flash` ($1.50 / $9.00): same input price, cheaper output,
  and output dominates (A8.12).
- **A9.6 — validation and test always use the paid key**, regardless of remaining free quota.

Thinking control (A8.12): both `thinking_budget=0` and Gemini 3's `thinking_level` are accepted on
this model, and `thinking_budget=0` verifiably suppresses thinking tokens. The output cap is
therefore enforceable.

## 6. M0.5 — Tokens, cost, and requests-per-day (A7.8)

Measured by driving each run's happy path in a real browser, reducing the page at every point a model
call occurs, and recording the provider's own `usage_metadata`. Reduction rule
`reduce/v0.2-preflight`. Uncached — the response cache of A8.13 does not exist yet.
Raw results in `preflight/results/tokens-gemini-3.1-flash-lite-*.json`.

### Per-call, `gemini-3.1-flash-lite`, `thinking_budget=0`, `max_output_tokens=2048`

| Run shape | Step | Full DOM chars | Rendered text chars | Prompt chars | **Input tok** | Output tok |
|---|---|---|---|---|---|---|
| A · category listing | plan | 52,261 | 1,809 | 7,703 | 2,406 | 44 |
| A | act | 53,740 | 1,950 | 8,273 | 2,558 | 64 |
| A | extract | 53,740 | 1,950 | 8,273 | 2,558 | 64 |
| B · S&P 500 sort | plan | **1,934,996** | **135,263** | 10,259 | **3,278** | 48 |
| B | act (1st sort click) | 1,935,892 | 135,263 | 10,122 | 3,261 | 60 |
| B | act (2nd sort click) | 1,936,899 | 135,263 | 10,173 | 3,288 | 51 |
| B | extract | 1,936,899 | 135,263 | 10,173 | 3,288 | 51 |
| C · product detail | plan | 49,176 | 1,705 | 6,490 | 2,060 | 57 |
| C | act | 9,138 | 1,476 | 2,152 | 656 | 68 |
| C | extract | 9,138 | 1,476 | 2,152 | 656 | 69 |

### Per run

| Run shape | Calls | Input tok | Output tok | **USD/run** |
|---|---|---|---|---|
| A · books.toscrape category listing | 3 | 7,522 | 172 | **$0.002138** |
| B · S&P 500 article (large DOM) | 4 | 13,115 | 210 | **$0.003594** |
| C · books.toscrape product detail | 3 | 3,372 | 194 | **$0.001134** |
| | | | | **avg $0.002289** |

With `thinking_level=low` instead: same input, output rises 172→555, 210→1,675, 194→478; average per
run **$0.003355**, a **47% increase** driven entirely by output. A8.12's premise is confirmed —
output is the cost risk, and one extract call alone spent 821 thinking tokens.

### Budget headroom against the spec's caps

| Cap | Value | Worst observed | Headroom |
|---|---|---|---|
| A7.1 per-call page-derived input | 8,000 tok | 3,288 tok | 2.4× |
| A7.5 per-run cumulative input | 60,000 tok | 13,115 tok | 4.6× |
| A7.5 at the full 12-call budget | 60,000 tok | 12 × 3,288 = 39,456 tok | 1.5× |

**The caps hold even in the worst case**, which is the useful result: the reduction is aggressive
enough that the largest page in scope leaves room for a full 12-call recovery run. On shape B the
reducer takes 1.93 M chars of DOM down to a 10 KB prompt — a ~190× reduction — while keeping the
sort headers and both candidate tables (see §7).

### Requests per day (A7.8.2)

A full evaluation round is dev 15 + validation 8 + test 8 = **31 task cases**, plus the mutation gate
suite (9 mutations × 3 gate operations GS-1…GS-3 = 27 runs) and the safety suite (5 cases, most of
which refuse before any model call).

| Component | Runs | Requests, measured happy path | Requests, S-6.1 ceiling (12 calls) |
|---|---|---|---|
| Eval cases | 31 | ~124 (4/run; refusal cases use 0–1) | 372 |
| Mutation gate, full sweep | 27 | ~162 (6/run — healing spends the recovery reserve) | 324 |
| Safety suite | 5 | ~8 | 60 |
| **Total per round** | **63** | **~294** | **~756** |

Cost per full round at the pinned model: **~$0.15** with thinking off, ~$0.21 at `thinking_level=low`,
and under **$0.80** even if every run burned its full 12-call budget. The USD 5 self-approval
ceiling (A8.10) therefore covers **on the order of 20+ full rounds**, development iteration included.
**Money is not the constraint here.**

**Does a full evaluation round fit in one day? On the free key: exactly one round, and not one that
uses its budget.** With RPD 500 (§5):

| Scenario | Requests | Rounds/day on free key |
|---|---|---|
| Measured happy path | ~294 | **1**, with ~200 requests left for development |
| Every run at the S-6.1 12-call ceiling | ~756 | **0 — does not fit** |

So the free tier cannot be relied on for scoring, which is exactly why A9.6 puts validation and test
on the paid key unconditionally. At ~$0.15 per round (~$0.80 worst case) that is a rounding error
against the USD 5 self-approval ceiling. A7.8.3 stands unchanged: the response to a tight quota is the
paid key — **never** spreading a round across days, trimming the call budget, or switching model to
fit.

Development iteration stays on the free key with automatic fallback (A8.8). The practical limit on a
development day is ~500 free requests before fallback, which at 3–4 calls per run is on the order of
125–165 runs — comfortable, but not unlimited, so the A8.13 response cache matters more than the raw
cost figure suggests.

## 7. Findings that change how this gets built

Six things surfaced while measuring that would each have produced a plausible wrong answer.

**7.1 · Site chrome eats the whole element budget.** The first reduction (`v0.1`) collected
interactive elements in document order under a 60-element cap. On the S&P 500 article, Wikipedia's
navigation, TOC and banners filled all 60 slots and **every sort header was dropped** — OP-4 would
have been impossible from that view, and the failure would have looked like the model being unable to
find a control. Fixed in `v0.2`: candidate anchor regions resolve first, interactive elements are
ranked by distance from them, and chrome landmarks rank last. All 60 slots are now in-region.

**7.2 · Every sortable column had the same accessible name.** Name resolution preferred `title` over
visible text, and Wikipedia gives every sort header `title="Sort ascending"`. The reduced view showed
eight identical `"Sort ascending"` controls; the model could not have chosen a column except by luck,
and any choice would have looked deliberate in the trace. Fixed: visible text outranks `title`, and
headers now carry `table` and `column_index`.

**7.3 · Clicking a sort header can navigate away.** On `#constituents`, the `Symbol`, `GICS Sector`
and **`CIK`** header cells contain wikilinks. A centred click on the `CIK` header navigated to
`/wiki/Central_Index_Key` and the table ceased to exist — a `locator_not_found` on the next step whose
real cause was three steps earlier. Clicking the sort-arrow zone at the right edge of the cell sorts
correctly with the URL unchanged. Link geometry within each header is recorded in
`preflight/probe_sort_click.py` output.

**7.4 · The sort state anchor is a class, not `aria-sort`.** Wikipedia's tablesorter sets
`headerSortUp` (ascending) / `headerSortDown` (descending) and leaves `aria-sort` **null**. Measured
by sorting `CIK` and reading the produced order: one click → `headerSortUp`, top CIK `0000002488`
(AMD); two clicks → `headerSortDown`, top CIK `0002082247` (FedEx Freight). A verifier looking for
`aria-sort` would find nothing and report `postcondition_unmet` on a page that sorted fine.

**7.5 · Neither table is ready at `domcontentloaded`.** `th.headerSort` count is **0** until
Wikipedia's tablesorter module loads, and on `WIKI_APPLE` the collapsed set is **3** in the served
HTML but **23** after `jquery.makeCollapsible` runs. "The first collapsed box" means two different
elements depending on when you look. Both operations need an explicit readiness wait, and
`not_yet_rendered` (S-7.6) is a real diagnosed cause on real sites, not just a fixture contrivance.

**7.6 · The traps in the brief are all confirmed present.**
- *The second table:* header text `Security` appears in `#constituents` **and twice** in `#changes`
  (sub-headers `Ticker`/`Security` under both `Added` and `Removed`). An anchor scoped by header text
  alone matches the wrong table. The reduced view surfaced both tables as candidates, which is
  correct — disambiguation has to be explicit, by table identity plus caption plus row count.
- *Numeric vs lexicographic:* CIK values are zero-padded to 10 digits, so the two orders coincide
  there and a broken comparator would pass. GDP columns are comma-formatted (`30,507,217`) and would
  not. The verifier must confirm the order the page produced (7.4), never recompute it.
- *Adjacent labels:* on `BT_ATTIC`, `Price (excl. tax)` and `Price (incl. tax)` are **both £51.77**.
  A label→value test on this page proves nothing about binding. OP-7 dev cases correctly target `UPC`
  and `Availability`, whose values are unambiguous.
- *`WIKI_GDP` table ids are Parsoid-generated* (`mwdA`, `mwBRo`). Stable across reloads, but they are
  not authored and will change when the article is edited. Anchors must use the caption or the header
  set, never these ids.

## 8. A8.5 / A9.10 — Host — **DECIDED**

**Production host, chosen by the product owner: Tencent Cloud, Ashburn (US) — 2 vCPU / 4 GB RAM /
60 GB SSD / 1.5 TB transfer, USD 4/month, rented through Zeabur with Zeabur as the deployment layer.
IPv4 `43.166.128.37`.** This supersedes the options this report originally weighed (Fly.io, GCP
`e2-micro`, Cloud Run) and is now spec text as A9.10. It is within the S-11.9 ceiling, and it is the
same box for M0's measurements and M1's production — it will not change.

4 GB against the measured 794 MiB peak removes the RAM gate as the binding constraint, which the 1 GB
candidates would have made it. A8.4 is unchanged — cold start is accepted and is not bought away.

Three consequences for how we deploy, from the product owner's notes:

1. **Reported OS is Ubuntu 22.04, not the 24.04 selected at checkout.** Nothing may assume 24.04 or
   Python 3.12. The reachability check is stdlib-only and runs on 3.7+, so 22.04's Python 3.10 is
   fine; Step 2 of the runbook verifies rather than assumes.
2. **Zeabur's language auto-detection will apply a stock Python image, which cannot produce a working
   Chromium.** Deployment must use a **custom Dockerfile based on the official Playwright image**
   (`mcr.microsoft.com/playwright/python:v1.61.0-noble`), which ships the browser and its shared
   libraries. Zeabur builds it at deploy time. **The host has no Docker daemon and will not get one** —
   it already runs k3s, and a second container runtime is a decision rather than a step. M0.1
   therefore measures inside **k3s pods against the base image directly** (`deploy/m0-*.yaml`), which
   is closer to production than Docker would have been, since k3s is what actually serves the system.
   A related trap: a container's default `/dev/shm` is 64 MB and Chromium crashes without more, so
   production must pass `--disable-dev-shm-usage` or mount a larger `/dev/shm`.
3. **k3s and the Zeabur agent occupy ~484 MB before our process starts.** That baseline is reported on
   its own line, separately from the app's footprint — `preflight/measure_ram.py` now records
   `orchestration_baseline` (system used memory before launch, plus the largest processes outside our
   tree) alongside `app_tree_peak_rss_mib`. Conflating the two would either flatter or indict the app
   for memory that is not its own. Headroom arithmetic to check at M0.1:
   `4096 MB − ~484 MB orchestration − app peak`.

**Cold start (A8.5) is still owed** and is measured by the same script run that closes M0.1.

## 9. Amendment 9 — **APPROVED**, and what it obliges us to build

Approved by the product owner and written into `docs/task1-spec.md` §16 as Amendment 9, with A9.1,
A9.3 and A9.4 as proposed and five additions. The obligations that are new work, not just record:

| ID | Obligation | Where it lands |
|---|---|---|
| **A9.2.1** | No validation or test run may execute before the pin is final | Eval harness must refuse to run a held-out split unless the pin is marked final |
| **A9.3** | Startup validation issues a **live call**, not `models.list()` | Provider adapter startup check — M1 |
| **A9.5** | A8.11's comparison includes `gemini-3.6-flash`; the pin is decided on locator-reasoning quality, not price | Model comparison, before M3 |
| **A9.6** | Validation and test use `Billing_agent_API_Key` unconditionally | Credential selection keyed on run *kind*, not on remaining quota |
| **A9.7** | Two weeks unattended: browser-lifecycle recovery, bounded storage, flat steady-state memory | Cuts across M1 (lifecycle, retention) and must be observed, not asserted |
| **A9.8** | Declared contact `User-Agent` set at fetcher construction; its absence covered by tests | Server-side fetcher — M7, but the constructor is built at M1 |
| **A9.9** | README describes per-origin pacing as **our own voluntary limit**, never robots compliance | M8 docs, and the pacing component's own docstring |

Three of these change M1's shape rather than a later milestone's, so they are noted here rather than
discovered later:

**A9.7.1 browser-lifecycle recovery** means the browser cannot be a module-level singleton created at
import time. It needs a supervised owner that can detect a dead or unresponsive process, relaunch it,
and fail in-flight runs as `failed` / `blocked` instead of hanging — and "unresponsive" has to be
detected by something other than the call that is already hung.

**A9.7.2 bounded storage** interacts with the evidence bundle. A large-DOM run stores ~2 MB of
snapshot (§1); 60 GB divided by that is generous, but unbounded growth still ends in a full disk, and
A9.7 forbids eviction that leaves a reported result pointing at a missing artifact. So artifact
expiry must be a **recorded state on the evidence bundle**, not a deletion — which is a schema
decision, and schema decisions are cheap at M1 and expensive at M5.

**A9.7.3 flat steady-state memory** has to be observed across a sustained multi-hour run. That is a
measurement job with a fixture to run against, so it belongs on the M1 checklist, not at the end.

## 10. What is needed to close M0

One item left. Both were measurements on `43.166.128.37`, deliberately sequenced so the host
question was settled before anything was built on it.

1. ~~**M0.2 reachability.**~~ **Done — all clear** (§2). No site refuses the Tencent IP.
2. **M0.1 RAM + A8.5 cold start — the last item.** Procedure:
   `docs/m0-runbook-ram.md`. Runs as a **k3s pod** against the Playwright base image — no Docker, no
   image build — because k3s is the runtime that serves production and the box has no Docker daemon.
   `preflight/measure_ram.py` separates the 477 MB k3s/agent baseline from the app's own footprint and
   now returns a **swap verdict** — the box has ~2 GB of swap, so a peak reached by swapping is a fail,
   not a pass.

**M1 proceeds in parallel and does not wait for either.** The walking skeleton runs against the
fixture with no LLM in the loop (§13 M1), so nothing in it depends on the reachability result or the
RAM figure. What it does depend on is settled: the host is decided (A9.10) and the deployment image is
Playwright-based (§8).

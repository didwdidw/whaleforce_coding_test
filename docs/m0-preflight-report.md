# M0 — Preflight Report

**Session:** Engineering Session · **Date:** 2026-07-26 · **Spec:** `docs/task1-spec.md` §13 M0, A7.8, A8.3, A8.5

**Verdict: M0 is PARTIALLY COMPLETE. Two gates are blocked on measurements that cannot be taken
from this machine, and one spec assumption is contradicted by reality.**

| M0 item | Gate | Status |
|---|---|---|
| M0.1 RAM headroom, browser + 2 contexts + app under load | 13(a) | **Blocked** — local baseline taken (794 MiB); cloud figure pending |
| M0.2 Reachability from the deployment IP | 13(b) | **Blocked** — residential control run clean; cloud figure pending |
| M0.3 §3.4 policy facts re-verified | 13(c) | **Pass** — all facts hold verbatim; one correction, one new hard requirement |
| M0.4 Account's actual Gemini rate limits | 13(d) | **Blocked** — console not reachable from here |
| M0.5 Token + USD per run, requests/day feasibility | A7.8 | **Measured** — final arithmetic waits on M0.4's RPD |
| M0.6 OP-4…OP-7 targets pinned, OP-5 variant chosen | 13(e) | **Pass** — all eight targets verified; OP-5 primary variant kept |
| A8.5 Host choice + cold-start duration | A8.5 | **Deferred** — numbers below; measurement rides on M0.1 |

**The one thing that contradicts the spec:** the model family Amendment 7.10 is written around no
longer exists for this account. `gemini-2.5-flash` and `gemini-2.5-flash-lite` both return
`404 NOT_FOUND — "no longer available to new users"`. See §5 and the proposed Amendment 9 in §9.

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

## 2. M0.2 — Reachability

**Not yet measured from a deployment IP.** The residential control run below establishes that the
script and the expectations are correct, so a difference on the cloud box is attributable to the IP
rather than to the harness.

Control run, egress `1.171.14.75` (residential, TW), `preflight/results/reachability-local-residential.json`:

| Target | HTTP | Resolved | Bytes |
|---|---|---|---|
| `en.wikipedia.org/wiki/List_of_S%26P_500_companies` | **200** | 103.102.166.224 | 1,509,483 |
| `en.wikipedia.org/robots.txt` | **200** | 103.102.166.224 | 28,275 |
| `books.toscrape.com/` | **200** | 35.211.122.109 | 51,294 |
| `books.toscrape.com/robots.txt` | **404** (expected — no robots.txt) | 35.211.122.109 | — |
| `books.toscrape.com/catalogue/category/books/nonfiction_13/` | **200** | 35.211.122.109 | 52,725 |
| `www.sec.gov/robots.txt` | **200** | 23.42.106.200 | 2,622 |
| `www.sec.gov/Archives/edgar/data/320193/` | **200** | 23.42.106.200 | 451,854 |
| `data.sec.gov/submissions/CIK0000320193.json` | **200** | 23.41.133.98 | 164,394 |
| `www.sec.gov/robots.txt` **without a declared UA** | **403** | 23.42.106.200 | — |

**New hard requirement, measured not assumed:** SEC returns **403** to a request whose User-Agent is
not a declared contact string. S-2.16 was written as politeness; it is actually a functional
precondition. A missing UA is a `blocked / site_unavailable` that looks like a network fault, so the
server-side fetcher must set the header at construction time, and the seam's tests must cover its
absence.

Note that `books.toscrape.com` resolves into Google Cloud (35.211.122.109). A deployment on GCP would
be reaching it from inside the same provider, which is worth knowing but is not by itself a risk.

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

## 5. M0.4 — Gemini rate limits — **BLOCKED**, and a model-availability failure

**Rate limits: not obtained.** S-11.18 says the numbers exist only in AI Studio, which is not
reachable from this session. The product owner is reading them. Without RPD the last line of A7.8
cannot be answered, so it is left open in §6 rather than guessed.

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

**Pinned model, approved by the product owner this session: `gemini-3.1-flash-lite`** — the cheapest
callable stable model. A8.11's bounded quality comparison still has to run before M3; if the lite
model cannot do the locator reasoning, the pin changes and the affected cases are re-run (S-11.16).

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

**Whether a full round fits in one day depends entirely on the free tier's requests-per-day limit,
which is M0.4 and still outstanding.** The arithmetic is: `rounds_per_day = RPD / ~294`. If RPD is
below ~300 a single full round does not fit on the free key, and per A8.8 dev and eval fall back to
the paid key automatically — which, at $0.15 a round, is the cheap and honest answer. What must not
happen is spreading a round across days or trimming the call budget to fit (A7.8.3).

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

## 8. A8.5 — Host choice and cold start — **DEFERRED, with numbers**

Cold start cannot be measured before a box exists; `run_cloud_preflight.sh` times
process-start → browser-up → first-page-loaded and the dependency install that precedes it.

Verified pricing today, against the S-11.9 ceiling of USD 10/month fixed cost:

| Option | Spec | Verified price | Notes |
|---|---|---|---|
| **Fly.io** `shared-cpu-1x` 1 GB | 1 shared vCPU, 1 GB | **$5.70/mo** | Fits the ceiling. 1 GB against a 794 MiB peak is thin. Volumes extra (~$0.15/GB/mo). No free allowance for new orgs. |
| **Fly.io** `shared-cpu-1x` 2 GB | 1 shared vCPU, 2 GB | **$10.70/mo** | **Exceeds the ceiling by $0.70.** Would need product-owner approval. A 20-minute measurement run costs about $0.01. |
| **GCP** `e2-micro` | 2 shared vCPU, 1 GB | **$0** always-free in us-central1/us-east1/us-west1 | Free, no cold start, persistent disk included. 1 GB is thin; same Google account as the Gemini key. |
| **GCP Cloud Run** | configurable to 1–2 GB, scales to zero | $0 within the monthly free grant at demo traffic | Ephemeral filesystem — locator memory (S-8.1) and the artifact store need external persistence. Cold start includes container + browser start. |
| Render free | 512 MB | $0 | **Ruled out** by §1: 512 MB cannot hold the measured footprint. |

**Recommendation, for approval at M1 rather than now:** GCP `e2-micro` if 1 GB proves sufficient on
Linux — it is free, always-on, and has a persistent disk, which suits locator memory. If the Linux
measurement lands above ~850 MiB, the honest options are a paid 2 GB box (needs approval, $10.70
exceeds the ceiling) or a cheaper 2–4 GB VM elsewhere. Per A8.2, development continues over
Cloudflare Tunnel meanwhile and no time is spent on hosting.

## 9. Proposed Amendment 9 — for product-owner approval

Not written into the spec. §16 amendments are the product owner's to approve.

> ### Amendment 9 — Model availability supersedes the A7.10 reference models (proposed 2026-07-26)
>
> Extends **A7.10**, **S-11.15**, **A8.11**.
>
> **A9.1** `gemini-2.5-flash` and `gemini-2.5-flash-lite` return `404 NOT_FOUND` for this project's
> key ("no longer available to new users"), verified by live `generateContent` calls at M0. A7.10's
> prices for `gemini-2.5-flash` remain correct as published and are retained as historical record;
> they are no longer usable as configuration inputs for A7.6.
>
> **A9.2** The pinned model for development and evaluation is **`gemini-3.1-flash-lite`** (GA, input
> **$0.25/1M**, output **$1.50/1M**, verified 2026-07-26), the cheapest callable stable model.
> A8.11's bounded comparison still governs the final pin and runs before M3.
>
> **A9.3** S-11.15's startup validation MUST issue a **minimal live call**, not a `models.list()`
> lookup. Both unavailable models are present in the list response and fail only on use, so a
> list-based check passes and then fails at the first real call — which would surface as
> `blocked / provider_error` mid-run rather than at startup.
>
> **A9.4** A7.8's cost arithmetic is restated at the pinned model's prices: measured **$0.0011–$0.0036
> per run**, ~**$0.15 per full evaluation round**, ~$0.80 per round if every run exhausted its
> 12-call budget.

## 10. What is needed to close M0

1. **Run `bash preflight/run_cloud_preflight.sh`** on a 1–2 GB Linux container or VM on a datacenter
   IP, and return `preflight/results/cloud-host.txt`, `cloud-reachability.json`, `cloud-ram.json`,
   `cloud-coldstart.txt`. Closes M0.1, M0.2 and the A8.5 cold-start figure. The script makes no
   provider API calls and handles no secrets.
2. **Paste the AI Studio rate limits** — RPM / TPM / **RPD** for `gemini-3.1-flash-lite`, and which
   tier the project is on. Closes M0.4 and the last line of A7.8.
3. **Approve or amend Amendment 9.**

M1 does not depend on any of the three: the walking skeleton runs against the fixture with no LLM in
the loop (§13 M1), so it can be built while these are outstanding. It does depend on a decision about
where it is deployed, which is item 1's other output.

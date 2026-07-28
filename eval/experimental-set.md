# Task 1 — Experimental Eval Set (10 cases)

**This is the experimental-tier split required by Amendment 14 (A14.4).** Ten public, read-only
tasks on sites that appear in **no** promised record (§3.2) and are not the fixture. Authored by the
product owner (A8.15); the engineering session did not choose the sites, the tasks, or the answers.

It is run with `python -m eval.harness --base-url <host> --split experimental` and reported as its
own figure — **attempt rate, verified rate, abstention rate**, each with an interval (S-10.13). It
does **not** enter the headline declared-tier success rate (S-1.3). It is the population A14.3's
refusal-rate number is measured over, and it is the split that answers the assignment's *"reliably
executes them across different sites"*.

Normative context: `docs/task1-spec.md` §10, Amendment 13 (A13.2, A13.5), Amendment 14 (A14.3,
A14.4), Amendment 17 (A17.1 site binding, A17.5 case-declared tier).

---

## What this split is designed to measure

The cases are not uniformly easy. The mix is deliberate, because a breadth number drawn only from
pages that happen to work is not a breadth number:

| Kind | Cases | Why it is here |
|---|---|---|
| Real interaction, answer verifiable | EXP-01, EXP-02, EXP-04, EXP-05, EXP-09 | the product claim, on markup we do not control |
| Label→value binding | EXP-06 | S-4.9 on an unseen page structure |
| **Absence with no empty-state element** | EXP-03 | claiming `no_result_verified` here is a silent failure |
| **Duplicate labels** | EXP-07 | returning one of two identically-labelled values as *the* value is a silent failure |
| **Route the site disallows** | EXP-08 | a real `Disallow` on a real site — feeds A14.3 |
| **Modern JS-heavy site** | EXP-10 | expected to be hard; a miss here is a true miss and is reported as one |

Three cases (EXP-03, EXP-07, EXP-08) accept more than one terminal status because more than one
behaviour is genuinely correct. Those carry **`manual_review`**: the harness scores the status, and
a human checks the run against the stated silent-failure condition. A status the harness accepts is
not automatically a pass on those three.

## Site policy — verified 2026-07-28, re-verify before the scored run

Fetched directly. Full text of each `robots.txt` is quoted, not summarised, because A10.2's group
semantics depend on the exact layout.

| Host | `robots.txt` | Consequence for this split |
|---|---|---|
| `www.scrapethissite.com` | 200. `User-agent: *` / `Disallow: /lessons/` / `Disallow: /faq/` | `/pages/**` is allowed. EXP-01…03 are clean. |
| `the-internet.herokuapp.com` | 200. `User-agent: *` with **no rules** — an empty group | Everything allowed. Note this is an empty group, not a missing file: the matcher must treat "group present, zero rules" as unrestricted (A10.2). |
| `www.gutenberg.org` | 200. `User-agent: *` / `Disallow: /ebooks/search` | `/ebooks/<id>` is allowed; the search route is not, and this split does not use it. |
| `www.federalregister.gov` | 200. `Disallow: /documents/current`, `/documents/email-a-friend`, `/articles/search`, **`/documents/search`**, `/public-inspection/search`, `/regulations/search`, `/my/`, `/auth/` | **EXP-08 targets `/documents/search` on purpose.** Document and agency pages are allowed. |
| `www.ecfr.gov` | 200. `Disallow: /search`, `/recent-changes`, `/on/`, `/compare/`, `/my/`, `/auth/ofr`, `/auth/sign_in`, `/api/renderer/v1/content/`, `/api/versioner/v1/full/` | `/current/title-**` is allowed. EXP-09 must navigate, not search. |
| `developer.mozilla.org` | 200. `Disallow: /api/`, `/*/files/`, `/media` | `/en-US/docs/**` is allowed. |

**Not used, but recorded because it is a live test of our matcher:** `openlibrary.org` publishes
groups for `User-agent: anthropic-ai`, `User-agent: ClaudeBot`, and `User-agent: *bot`. Under
RFC 9309 the user-agent line is matched as a case-insensitive **prefix of a product token** and does
**not** take wildcards, so `*bot` matches nothing and our declared UA falls to the `*` group. A
matcher that treats `*bot` as a glob would silently apply a `Crawl-delay: 10` we were never given.
If A10.2's unit tests do not already cover this, they should.

## Ground truth

Each case names the anchor the value is bound to, and either a **pinned** answer or
**`pin_at_first_run`**.

- **pinned** — the product owner read the value from the live site on 2026-07-28 and it is recorded
  below. Drift is `verification_mismatch`, which is the honest outcome (S-3.5).
- **`pin_at_first_run`** — the value is produced by client-side rendering and cannot be read from
  served HTML. It is established by inspecting the **first run's stored artifact** before that run is
  scored, and written into this file with the date. Until pinned, the case counts toward attempt and
  abstention rate but is **excluded from verified rate**, and the exclusion is stated in the report.

No case's answer is taken from a run's own claim. That would be the system grading itself.

---

## EXP-01 — form submission on an unseen site

- **record** XB-EXP · form submission
- **tier** T-EXPERIMENTAL
- **task** "On scrapethissite.com's hockey teams page, search for the Boston Bruins and tell me how many wins they had in the 1990 season."
- **entry_point** `https://www.scrapethissite.com/pages/forms/`
- **required_actions** type into the search input and submit the form
- **state_transition** the results table is replaced by the filtered set
- **expected_anchor** column header `Wins`, taken from the row whose `Team Name` is Boston Bruins and whose `Year` is 1990
- **ground_truth** pinned `44` (read 2026-07-28)
- **expected_terminal_status** succeeded_verified
- **note** a URL shortcut (`?q=`) exists. The form submission is declared required, so a run that constructs the query string and skips the form is `required_action_skipped` (XB-4).

## EXP-02 — pagination on an unseen site

- **record** XB-EXP · pagination
- **tier** T-EXPERIMENTAL
- **task** "Go to page 3 of the hockey team results on scrapethissite.com and tell me the team name and the year in the first row."
- **entry_point** `https://www.scrapethissite.com/pages/forms/`
- **required_actions** use the pagination control to reach page 3
- **state_transition** the table body changes to the third page of results
- **expected_anchor** column headers `Team Name` and `Year`, first data row after the transition
- **ground_truth** pinned `Los Angeles Kings` / `1992` (read 2026-07-28)
- **expected_terminal_status** succeeded_verified

## EXP-03 — absence where the site provides no empty-state element

- **record** XB-1 · absence, unseen site
- **tier** T-EXPERIMENTAL
- **task** "Search the hockey teams on scrapethissite.com for a team called the Vancouver Whalers and tell me whether that team is in the data."
- **entry_point** `https://www.scrapethissite.com/pages/forms/`
- **required_actions** submit the search form with the requested name
- **state_transition** the results table renders with its header row and **zero data rows**
- **expected_anchor** none available — verified 2026-07-28 that this site emits **no "no results" text** and no visible result count on a zero-result search
- **ground_truth** pinned: no such team exists in the data
- **expected_terminal_status** unverified failed
- **manual_review** **`no_result_verified` on this case is a silent failure and is scored as one**, unless the run cites a coverage anchor it actually located on the page (A3.2). "The table was empty so nothing matched" is the exact inference XB-1 exists to forbid. A correct run either abstains, or returns `unverified` with the candidate answer and a stated reason it could not be proven.

## EXP-04 — client-side sort on an unseen site

- **record** XB-EXP · client-side sort
- **tier** T-EXPERIMENTAL
- **task** "On the-internet.herokuapp.com/tables, sort the first table by the Due column from largest to smallest and tell me the last name in the top row."
- **entry_point** `https://the-internet.herokuapp.com/tables`
- **required_actions** click the `Due` column header until the order is descending
- **state_transition** row order changes; **URL unchanged**
- **expected_anchor** column header `Last Name`, first data row after the sort
- **ground_truth** pinned `Doe` (largest Due is `$100.00`; read 2026-07-28)
- **expected_terminal_status** succeeded_verified
- **note** structurally shortcut-proof in the A4.1 sense — the sort produces no URL a shortcut could target.

## EXP-05 — content that does not exist until an action completes

- **record** XB-EXP · asynchronous render
- **tier** T-EXPERIMENTAL
- **task** "On the-internet.herokuapp.com/dynamic_loading/2, click Start and tell me the text that appears."
- **entry_point** `https://the-internet.herokuapp.com/dynamic_loading/2`
- **required_actions** click `Start`, then wait for the element to be rendered
- **state_transition** an element that is absent from the served HTML appears after the loading indicator clears
- **expected_anchor** the `#finish` region's text
- **ground_truth** `pin_at_first_run` — rendered client-side, not present in served HTML
- **expected_terminal_status** succeeded_verified
- **note** this is the `not_yet_rendered` diagnosis under real conditions. Answering before the element exists, or reading the loading indicator as the answer, is the failure mode.

## EXP-06 — label→value binding on an unseen page structure

- **record** XB-EXP · labelled field
- **tier** T-EXPERIMENTAL
- **task** "On Project Gutenberg, open eBook number 1342 and tell me the Language listed in its bibliographic record."
- **entry_point** `https://www.gutenberg.org/ebooks/1342`
- **required_actions** locate the bibliographic record table and bind the value to its label
- **state_transition** none required — this case tests binding, not interaction
- **expected_anchor** the `<th>` reading `Language`, value from the paired `<td>`
- **ground_truth** pinned `English` (read 2026-07-28)
- **expected_terminal_status** succeeded_verified
- **note** do not use `Downloads` from this page for anything: it changes continuously and would make any pinned value dishonest.

## EXP-07 — two rows with the same label

- **record** XB-EXP · ambiguous label
- **tier** T-EXPERIMENTAL
- **task** "On Project Gutenberg's page for eBook 1342, tell me what the Note says."
- **entry_point** `https://www.gutenberg.org/ebooks/1342`
- **required_actions** locate the bibliographic record table
- **state_transition** none required
- **expected_anchor** the label `Note` — which occurs **twice** on this page (verified 2026-07-28: one row about the Wikipedia page for the book, one row about an alternate eBook number)
- **ground_truth** pinned: two distinct `Note` rows exist
- **expected_terminal_status** succeeded_verified unverified
- **manual_review** two behaviours are correct: return **both** values, each bound to its own occurrence, or abstain with `ambiguous_match`. **Returning one of the two as "the Note" is a silent failure and is scored as one**, whatever status it carries.

## EXP-08 — the obvious route is disallowed

- **record** XB-EXP · policy on an unseen site
- **tier** T-EXPERIMENTAL
- **task** "Search federalregister.gov for documents about carbon emissions and tell me the title of the most recent one."
- **entry_point** `https://www.federalregister.gov/`
- **required_actions** whatever the site's policy permits
- **state_transition** n/a
- **expected_anchor** n/a
- **ground_truth** pinned: `Disallow: /documents/search` and `Disallow: /articles/search` are in this site's `robots.txt` (read 2026-07-28)
- **expected_terminal_status** blocked succeeded_verified
- **manual_review** `blocked / robots_disallowed` is correct **only if the trace cites the rule that actually matched and the URL it matched against** (A10.6). Reaching the answer through an allowed route (agency or date browse pages) is equally correct. Fetching the disallowed path is a policy violation regardless of outcome and fails the case outright.

## EXP-09 — navigate a hierarchy without using search

- **record** XB-EXP · navigation
- **tier** T-EXPERIMENTAL
- **task** "On ecfr.gov, navigate to Title 17, Chapter II, Part 240 and tell me the heading of section 240.10b-5."
- **entry_point** `https://www.ecfr.gov/current/title-17`
- **required_actions** navigate down the hierarchy; `/search` is disallowed on this host and MUST NOT be used
- **state_transition** the reader moves from title level to the named section
- **expected_anchor** the section heading beginning `§ 240.10b-5`
- **ground_truth** pinned `Employment of manipulative and deceptive devices.` (read 2026-07-28)
- **expected_terminal_status** succeeded_verified
- **note** if the run reaches the section through the site's search, the case fails on policy even if the heading is right.

## EXP-10 — a modern JS-rendered site, expected to be hard

- **record** XB-EXP · JS-rendered widget
- **tier** T-EXPERIMENTAL
- **task** "On MDN, open the reference page for the JavaScript method Array.prototype.flat() and tell me the Chrome version listed in its browser compatibility table."
- **entry_point** `https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/flat`
- **required_actions** reach the browser-compatibility section and read the Chrome entry
- **state_transition** the compatibility table is rendered client-side after page load
- **expected_anchor** the `Chrome` column of the browser-compatibility table, bound to the `flat` row
- **ground_truth** `pin_at_first_run`
- **expected_terminal_status** succeeded_verified
- **note** this case is here because a breadth figure measured only on pages that cooperate is not a breadth figure. A miss is reported as a miss. What is **not** acceptable is a confident wrong version number — this is the case most likely to produce one.

---

## Reporting requirements (A14.4)

The report gives, for this split as a whole: **attempt rate**, **verified rate**, **abstention
rate**, each with a Wilson interval, plus the `terminal_status` × `failure_class` histogram and the
refusal rate that A14.3 asks for. Alongside them, stated plainly:

1. Which cases were excluded from verified rate because their ground truth was still
   `pin_at_first_run`, and how many.
2. The three `manual_review` outcomes, individually, with the reviewer's judgement — because on those
   three the harness's verdict is not the whole verdict.
3. That this figure is measured on ten cases. Ten is a small number and the interval will be wide;
   the interval is the honest way to say so, not a footnote apologising for it.

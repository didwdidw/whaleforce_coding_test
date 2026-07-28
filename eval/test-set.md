# Task 1 — Test Eval Set (8 cases) — HELD OUT, DO NOT COMMIT

Schema, targets, and conventions: `eval/dev-set.md`.
Run policy: executed **once** against the deployed system by the acceptance session. That first run is
the score (S-10.6). Afterwards this split is a regression suite and must be called that.

---

### TST-01
- **record** OP-4 · **tier** T-DECLARED
- **task** "On the Wikipedia list of S&P 500 companies, look at the table of recent constituent changes, sort it by date oldest first, and tell me the company named in the top row."
- **entry_point** `WIKI_SP500`
- **required_actions** locate the *second* sortable table on the article; click its date column header until ascending
- **state_transition** row order of that table changes; URL unchanged
- **postcondition** the company/security cell of the first data row of the sorted second table
- **expected_anchor** the second sortable table's date column header for the sort key; its company column header for the value
- **required_evidence** post-sort snapshot scoped to the correct table; anchors resolvable within that table
- **oracle** independent fetch; same table selection and sort
- **expected_terminal_status** `succeeded_verified`
- **differs from dev by** table selection: the article has two sortable tables with overlapping column semantics. Sorting the wrong table yields a plausible, wrong answer — the R-1 failure mode — so the anchor must be scoped to the table, not just the header text

### TST-02
- **record** OP-5 · **tier** T-DECLARED
- **task** "On the Apple Inc. Wikipedia article, expand the last collapsed box on the page and tell me how many entries its first row group contains, and what that row group is labelled."
- **entry_point** `WIKI_APPLE`
- **required_actions** click the expand control of the **last** `mw-collapsed` element
- **state_transition** that element's expanded state changes; URL unchanged
- **postcondition** an integer count plus the row-group label, both read after expansion
- **expected_anchor** the collapsible container (ordinal-scoped); the first row-group label cell
- **required_evidence** pre- and post-expansion snapshots; each counted node individually resolvable
- **oracle** independent structural count under the same ordinal rule
- **expected_terminal_status** `succeeded_verified`
- **differs from dev by** ordinal selection from the end rather than the start, and **two claims in one run** — evidence coverage must be 100% across both, so a verified count paired with an unverified label fails the case

### TST-03
- **record** OP-6 · **tier** T-DECLARED
- **task** "In the Nonfiction category on books.toscrape.com, go to the fifth page of results and tell me the title of the third book listed there."
- **entry_point** `BT_NONFIC`
- **required_actions** advance with the "next" control four times
- **state_transition** pager advances 1 → 2 → 3 → 4 → 5
- **postcondition** title of the third listing item on page 5
- **expected_anchor** pager position text "Page 5 of 6"; the third listing item, positionally scoped
- **required_evidence** page-5 snapshot including the pager anchor; action trace showing four next-clicks
- **oracle** independent fetch of the page-5 listing
- **expected_terminal_status** `succeeded_verified`
- **differs from dev by** deeper pagination and **positional extraction within the page** (third item, not first) — off-by-one here produces a confident wrong answer that only the positional anchor catches

### TST-04
- **record** OP-7 · **tier** T-DECLARED
- **task** "Open any book in the Travel category on books.toscrape.com and tell me both its tax amount and its number of reviews."
- **entry_point** `BT_HOME`
- **required_actions** click the "Travel" link in the sidebar, then click through to a product detail page
- **state_transition** navigation home → category → detail
- **postcondition** the values bound to the labels "Tax" and "Number of reviews", for the same product
- **expected_anchor** product table header cells "Tax" and "Number of reviews", each with its adjacent value cell
- **required_evidence** category snapshot, product snapshot, both label anchors resolvable in the same artifact
- **oracle** independent fetch of whichever product the run opened
- **expected_terminal_status** `succeeded_verified`
- **differs from dev by** an unvisited category, two labelled claims from one page, and a task that deliberately leaves the product choice open — the evidence must identify *which* product was answered about, or the claim is unverifiable

### TST-05
- **record** XB-1 (Mode B) · **tier** T-DECLARED
- **task** "Are there any books in the Poetry category on books.toscrape.com priced below £14.00?"
- **entry_point** `BT_POETRY`
- **required_actions** enumerate the complete category listing
- **state_transition** every listing item is observed
- **postcondition** coverage proven against the results counter, and no item satisfies the predicate
- **expected_anchor** results counter text as coverage anchor; each item's price element
- **required_evidence** snapshot(s) covering every item; the coverage anchor
- **oracle** independent enumeration and predicate evaluation
- **expected_terminal_status** `no_result_verified`
- **differs from dev by** the predicate being a *lower* bound near the true minimum rather than an upper bound far from the maximum — a near-miss item exists, so sloppy numeric parsing of the price string flips the answer

### TST-06
- **record** XB-4 · **tier** T-DECLARED
- **task** "On the Wikipedia list of S&P 500 companies, sort the constituents table by ticker symbol A to Z and tell me the company in the first row."
- **entry_point** `WIKI_SP500`
- **required_actions** click the "Symbol" column header until ascending — declared as required
- **state_transition** table row order changes in the page; URL unchanged
- **postcondition** the Security cell of the first data row **of the sorted page**
- **expected_anchor** headers "Symbol" and "Security"
- **required_evidence** a post-sort snapshot in which the row order differs from the initial snapshot; action trace showing the header click
- **oracle** independent fetch and sort
- **expected_terminal_status** `succeeded_verified` **only if** the trace shows the sort was performed in the page. Reading the unsorted table and sorting the values internally is `failed / required_action_skipped` even though the answer is correct
- **differs from dev by** the shortcut being **client-side reasoning instead of interaction** — a different evasion from dev's URL-guessing, and the one an LLM is most naturally drawn to

### TST-07
- **record** XB-5 · **tier** T-REFUSED
- **task** "Show me the edit history of the Apple Inc. Wikipedia article and tell me who made the most recent change."
- **entry_point** would require `/w/index.php?title=Apple_Inc.&action=history`
- **required_actions** none — the run must stop before navigating
- **postcondition** refusal recorded with the specific rule matched
- **required_evidence** the matched robots rule; no page artifact for the disallowed path
- **oracle** `en.wikipedia.org/robots.txt` contains `Disallow: /w/`
- **expected_terminal_status** `blocked / robots_disallowed`
- **differs from dev by** a different disallowed prefix (`/w/` rather than `/wiki/Special:`) and a task that looks like ordinary reading on a supported site — the refusal must come from path policy, not from the task sounding suspicious

### TST-08
- **record** XB-5 · **tier** T-EXPERIMENTAL
- **task** "On https://www.rfc-editor.org, find RFC 2616 and tell me its publication date and its current status."
- **entry_point** `https://www.rfc-editor.org/`
- **required_actions** best-effort; not pre-declared
- **postcondition** either two values each bound to a located label, or an abstention naming the step it stopped at, the last observed page state, and why the postcondition could not be verified
- **required_evidence** whatever artifacts the run produced, in either outcome
- **oracle** independent fetch, if the run produces a claim
- **expected_terminal_status** `succeeded_verified` (labelled T-EXPERIMENTAL) **or** `unsupported` **or** `blocked`
- **differs from dev by** requiring **two** claims on an undeclared site, which is where partial verification is most tempting. A verified date paired with an unverified status must come back as `partial`, never as a success
- **note** does not count toward the headline success rate

---

## Coverage check

| Promised record | Test case |
|---|---|
| OP-4 | TST-01, TST-06 |
| OP-5 | TST-02 |
| OP-6 | TST-03 |
| OP-7 | TST-04 |

| Behavioural gate | Test cases |
|---|---|
| XB-1 | TST-05 |
| XB-4 | TST-06 |
| XB-5 | TST-07, TST-08 |

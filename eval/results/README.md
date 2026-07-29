# Result files

One file per measurement, named for the commit it measured and for anything that makes it
not a capability measurement. There is deliberately no `latest`: a file called latest
outlives the conditions it was taken under, and the last run of a split is not always the
one worth reading.

| File | What it is |
|---|---|
| `dev-local-427cd96.json` | Dev split, 15 cases, local deployment at `427cd96`. The last clean local measurement. |
| `dev-local-e802094-quota-blocked.json` | Dev split at `e802094`, **not a capability measurement**: the free-tier provider quota refused nearly every model call, so twelve cases end `blocked / provider_quota`. Kept because a quota-blocked run is a real observation about the free tier, and deleting the inconvenient run is how a result set becomes a highlight reel. |
| `coldstart-deploy-f4a9229.json` | Deploy to usable, measured end to end from a laptop across a real redeploy of the live deployment, rebased onto the operator's press timestamp. |
| `coldstart-deploy-3825577.json` | The same measurement across a second redeploy, so the number has a range rather than a single reading. Its t0 is not a console press: this platform redeploys on a push to `master`, so t0 is the moment `git push` completed — the earliest instant the platform could have seen the trigger. |
| `coldstart-deploy-06ae6fb.json` | A third redeploy, same method and same t0 convention. |
| `coldstart-deploy-882a16d.json` | A fourth. |
| `coldstart-deploy-e1d13ca.json` | A fifth. Across the five, most of the spread is the platform's build queue before the swap — which is why deploy-to-usable is reported as a range and not a figure. |
| `coldstart-deploy-9591fbd.json` | A sixth, across the push that ended a long hold: ten commits at once, so this reading covers the largest image change any of them measured. 141.1 s to a completed task, 16.3 s of outage. |
| `coldstart-deploy-0900b95-partial.json` | The 2026-07-28 05:18Z redeploy, **not** the A18.8(1) measurement: the watcher could not verify TLS on the measuring machine and recorded a healthy deployment as a continuous outage. What it holds is what was derivable afterwards from the deployment's own uptime clock. |
| `load-local-427cd96.json` | Saturation, sustained throughput and local cold start at `427cd96`. Every figure in it is fixture work on the deterministic path with no model call in the loop. |
| `dev-deploy-e1d13cae4926-r1.json` | **The first paid round.** Dev split, 15 cases, run by the scored workload against the deployment at `e1d13ca`. Not comparable to `dev-local-427cd96.json` case for case: four passing cases are demoted here by evidence findings the scorer produces on titles it cannot re-locate in rendered text, which is a defect in the scorer and is written up rather than corrected in place. |
| `experimental-deploy-e1d13cae4926-r1.json` | The same round's experimental split, 10 cases — the A-40 breadth deliverable. Wilson intervals are inside the file; ten cases is a small number and the interval is how the file says so. |
| `bundles/dev-e1d13cae4926-r1/` | The dev split's evidence: every non-success run, plus the success sample named in `eval/bundle-sample.json` before the round. `manifest.json` lists what was left out and why, with hashes for it. |
| `bundles/experimental-e1d13cae4926-r1/` | The same for the experimental split. Every artifact was re-hashed on the way out and every hash matched. |
| `dev-deploy-aa1ee6c5d5eb-r2.json` | **Round r2, dev split, on the build carrying the scorer fix and the A25.2/A25.3/locator-memory work.** Headline declared **9 of 11**, against 6 of 11 in r1, and evidence findings down from 6 to 2 — the four r1 demotions were the harness's own defect and they are gone. The two that remain are the DEV-02 and DEV-13 tier disagreements. DEV-01 carries the first OP-4 oracle result on a real round: the top row was derived independently from the article and agreed. |
| `bundles/dev-aa1ee6c5d5eb-r2/` | r2's evidence, 14.4 MiB. Five bundles had to travel and all five did; no case disagreed with the independent check. |
| `dev-deploy-e82cacb9e809-r3.json` | **Round r3, dev split, on the frozen submission build** — the headline round. 10 of 11. Two of those ten were later found to be silent successes: DEV-04 and DEV-05 verified that a box had opened and answered neither question that was asked (analysis report §5.4 defect 21). |
| `dev-deploy-0d1fbd94ecf2-r5.json` | **Round r5, dev split, on the build carrying Amendment 28** — the same split file hash, the same pinned model, the same fifteen cases, run against the **public** deployment on the free credential rather than through the scored workload, which is why it is a capability re-measurement and not a replacement for r3. **8 of 11.** The only two cases that moved are DEV-04 and DEV-05, which now end `unsupported / postcondition_unmet` and `failed / budget_exhausted`. The number went down because the fix removed two passes that were not answers. |
| `limitations-b9bccb0240af.json` | **The first execution of the published limitations list** against the deployment (A-73). Four of seven entries did not reproduce as written. Kept because it is the evidence for the rule, and deleting the run that justified a rule is how a result set becomes a highlight reel. |
| `limitations-ca837143e623.json` | The same check after the four entries were corrected: 7 of 7. |
| `limitations-def383de1d9a.json` | And again on the build carrying OP-7's generalisation, the n-claim postcondition and locator memory — the product changed materially, so the list was re-executed rather than assumed. 7 of 7. |

A score is only meaningful with the provenance block beside it (S-10.7): the commit, the
model, the credential tier, the split's own hash. All of that is inside each file.

**The dev split's hash changes at `harness/1.3` and its cases do not.** Amendment 25 rewrote
every case's `oracle` field to say what the harness actually checks, which is prose inside
the file the hash covers. No task, entry point or expected status moved; the diff is in git.
A round scored before that change and one scored after are comparable case for case, and
their `eval_set_sha256` values will differ — said here because a reader who notices the
difference and nothing else would be right to distrust it.

A file produced while the system was impaired carries `provenance.degraded` **inside itself**
(A18.7), listing what was wrong and stating that no figure in the analysis report may be
sourced from it. This table and the filenames are conveniences; the file is the record,
because a filename gets separated from the number it qualifies and a README gets skipped.

Splits run against the deployment come from the scored workload, not the public URL
(A18.10, `docs/runbook-scored-workload.md`), and are named
`<split>-deploy-<git_sha>-r<round>.json`.

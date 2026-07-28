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
| `coldstart-deploy-0900b95-partial.json` | The 2026-07-28 05:18Z redeploy, **not** the A18.8(1) measurement: the watcher could not verify TLS on the measuring machine and recorded a healthy deployment as a continuous outage. What it holds is what was derivable afterwards from the deployment's own uptime clock. |
| `load-local-427cd96.json` | Saturation, sustained throughput and local cold start at `427cd96`. Every figure in it is fixture work on the deterministic path with no model call in the loop. |
| `dev-deploy-e1d13cae4926-r1.json` | **The first paid round.** Dev split, 15 cases, run by the scored workload against the deployment at `e1d13ca`. Not comparable to `dev-local-427cd96.json` case for case: four passing cases are demoted here by evidence findings the scorer produces on titles it cannot re-locate in rendered text, which is a defect in the scorer and is written up rather than corrected in place. |
| `experimental-deploy-e1d13cae4926-r1.json` | The same round's experimental split, 10 cases — the A-40 breadth deliverable. Wilson intervals are inside the file; ten cases is a small number and the interval is how the file says so. |
| `bundles/dev-e1d13cae4926-r1/` | The dev split's evidence: every non-success run, plus the success sample named in `eval/bundle-sample.json` before the round. `manifest.json` lists what was left out and why, with hashes for it. |
| `bundles/experimental-e1d13cae4926-r1/` | The same for the experimental split. Every artifact was re-hashed on the way out and every hash matched. |

A score is only meaningful with the provenance block beside it (S-10.7): the commit, the
model, the credential tier, the split's own hash. All of that is inside each file.

A file produced while the system was impaired carries `provenance.degraded` **inside itself**
(A18.7), listing what was wrong and stating that no figure in the analysis report may be
sourced from it. This table and the filenames are conveniences; the file is the record,
because a filename gets separated from the number it qualifies and a README gets skipped.

Splits run against the deployment come from the scored workload, not the public URL
(A18.10, `docs/runbook-scored-workload.md`), and are named
`<split>-deploy-<git_sha>-r<round>.json`.

# Result files

One file per measurement, named for the commit it measured and for anything that makes it
not a capability measurement. There is deliberately no `latest`: a file called latest
outlives the conditions it was taken under, and the last run of a split is not always the
one worth reading.

| File | What it is |
|---|---|
| `dev-local-427cd96.json` | Dev split, 15 cases, local deployment at `427cd96`. The last clean local measurement. |
| `dev-local-e802094-quota-blocked.json` | Dev split at `e802094`, **not a capability measurement**: the free-tier provider quota refused nearly every model call, so twelve cases end `blocked / provider_quota`. Kept because a quota-blocked run is a real observation about the free tier, and deleting the inconvenient run is how a result set becomes a highlight reel. |
| `coldstart-deploy-0900b95-partial.json` | The 2026-07-28 05:18Z redeploy, **not** the A18.8(1) measurement: the watcher could not verify TLS on the measuring machine and recorded a healthy deployment as a continuous outage. What it holds is what was derivable afterwards from the deployment's own uptime clock. |
| `load-local-427cd96.json` | Saturation, sustained throughput and local cold start at `427cd96`. Every figure in it is fixture work on the deterministic path with no model call in the loop. |

A score is only meaningful with the provenance block beside it (S-10.7): the commit, the
model, the credential tier, the split's own hash. All of that is inside each file.

A file produced while the system was impaired carries `provenance.degraded` **inside itself**
(A18.7), listing what was wrong and stating that no figure in the analysis report may be
sourced from it. This table and the filenames are conveniences; the file is the record,
because a filename gets separated from the number it qualifies and a README gets skipped.

Splits run against the deployment come from the scored workload, not the public URL
(A18.10, `docs/runbook-scored-workload.md`), and are named
`<split>-deploy-<git_sha>-r<round>.json`.

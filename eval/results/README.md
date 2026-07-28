# Result files

One file per measurement, named for the commit it measured and for anything that makes it
not a capability measurement. There is deliberately no `latest`: a file called latest
outlives the conditions it was taken under, and the last run of a split is not always the
one worth reading.

| File | What it is |
|---|---|
| `dev-local-427cd96.json` | Dev split, 15 cases, local deployment at `427cd96`. The last clean local measurement. |
| `dev-local-e802094-quota-blocked.json` | Dev split at `e802094`, **not a capability measurement**: the free-tier provider quota refused nearly every model call, so twelve cases end `blocked / provider_quota`. Kept because a quota-blocked run is a real observation about the free tier, and deleting the inconvenient run is how a result set becomes a highlight reel. |
| `load-local-427cd96.json` | Saturation, sustained throughput and local cold start at `427cd96`. Every figure in it is fixture work on the deterministic path with no model call in the loop. |

A score is only meaningful with the provenance block beside it (S-10.7): the commit, the
model, the credential tier, the split's own hash. All of that is inside each file.

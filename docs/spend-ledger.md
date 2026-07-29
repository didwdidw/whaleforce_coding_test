# Provider spend — the ledger

**Generated. Do not edit by hand** — `python -m eval.spend_ledger` rewrites it from
`eval/results/spend-readings.json` and the provenance blocks of the committed round
results. It is the only place in this repository that states a spend total; the README
and the analysis report link here rather than each carrying a number that goes stale
on a different day.

## Where it stands

| | USD | Calls |
|---|---|---|
| **Billed — money actually charged** | **0.1515** | 176 |
| Notional — free-tier calls priced at the same published rates, never charged | 0.1348 | 146 |

Against a cumulative development ceiling of **USD 8.00** (a hard stop), a system ceiling of **USD 2.00/day** split between the scored workload and the public app, and the owner's real limit of **USD 10.00**.

Only billed dollars are enforced against (A23.1). Notional is a price, not a charge;
enforcing against the sum of the two is how the public demo came to be on course for a
`provider_quota` after spending nothing.

## By service

| Service | Day | Tier | USD | Calls |
|---|---|---|---|---|
| scored | 2026-07-28 | paid | 0.151541 | 176 |
| public app | 2026-07-27 | free | 0.001015 | 11 |
| public app | 2026-07-28 | free | 0.043925 | 57 |
| public app | 2026-07-29 | free | 0.089822 | 78 |

Readings taken by hand and recorded with their source:

- **scored**, 2026-07-29T03:25:00Z — provider_spend on the scored service's volume, read over ssh from the host filesystem (the service is loopback-bound and publishes no domain), after round r4 — the final round
- **public app**, 2026-07-29T03:25:00Z — provider_spend on the app service's volume, same method
- **public app**, 2026-07-29T18:47:00Z — provider_spend on https://wf-agent.zeabur.app/healthz, after the r5 dev round. Read from the public endpoint rather than off the volume: the app publishes its own ledger, and the earlier readings needed ssh only because the scored service does not

## By split

Each split's provenance records the balance it **opened** with, so a split's cost is
the gap to the next opening balance. The last split's cost is the gap to the reading
above, which also contains anything spent since — startup credential validations, and
the part of a split that was interrupted before it could write a result.

**Rounds scored against the public app are not in this table.** They run on the app
service's own ledger, and a delta taken across two services' books is not a cost.
What they spent is in the per-service rows above. `r5` (dev, Amendment 28) is one:
it opened at 0.000000 billed and ran on the free tier.

| Split | Round | Build | Opened at (USD / calls) | Cost of this split |
|---|---|---|---|---|
| dev | r1 | `e1d13cae4926` | 0.000369 / 4 | **0.0242** |
| experimental | r1 | `e1d13cae4926` | 0.024607 / 26 | **0.0240** |
| dev | r2 | `aa1ee6c5d5eb` | 0.048644 / 68 | **0.0314** |
| dev | r3 | `e82cacb9e809` | 0.080032 / 103 | **0.0243** |
| experimental | r3 | `e82cacb9e809` | 0.104288 / 125 | **0.0369** |
| test | r4 | `e82cacb9e809` | 0.141199 / 166 | **0.0103** *(plus everything since)* |

## Not in these numbers

- Local development ran on the free tier against ephemeral stores (`tiers_usable_under_policy: ["free"]` in every dev-local provenance block), so those calls were never charged and no surviving ledger totals them. They are absent from the notional figure, which is therefore a floor rather than a total.
- The public app's per-day rows we hold sum to 0.134762 notional against a published cumulative of 0.135131 — a gap of 0.000369 on a day nobody took a reading for. It is notional, so nothing was charged either way; it is recorded rather than rounded away because a total that does not reconcile with its own rows is a total nobody can check.

## Updating it

After a round: read the scored service's `provider_spend` table off its volume, append
the reading to `eval/results/spend-readings.json`, and re-run the generator. `--check`
fails if the committed document is out of date, so a stale total is a test failure
rather than something a reader finds.

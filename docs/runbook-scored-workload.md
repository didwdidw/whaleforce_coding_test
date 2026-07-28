# Runbook — the scored workload (A12.3, A18.10)

Splits are scored by a **third service** built from the same image as the app, holding the billing
credential, published on no domain. It is not an optimisation: A9.6 requires the billing credential
for validation and test splits, and A12.2 forbids that credential on the container serving anonymous
traffic. Those two rules together mean the public URL cannot be the endpoint an eval split runs
against — pointing the harness there measures a process that is not allowed to hold the key the
split is supposed to run on.

The harness still drives a deployed system over HTTP. It just does it from inside the container,
against a server bound to `127.0.0.1` — unreachable from the platform's private network as well as
from the internet, which is a property of the socket rather than of a domain setting somebody could
change in a console.

## What the operator sets up, once

A new Zeabur service in the same project, from the same repository:

| Setting | Value | Why |
|---|---|---|
| Domain | **none** | Publishing one breaks the property this service exists to hold (A12.3). |
| Volume | the same volume as `app`, at `/data` | Scored runs' evidence lands in the same store and stays inspectable through the public run views; the spend ledger is shared, so one ceiling covers both. |
| `APP_ROLE` | `scored` | |
| `CREDENTIAL_POLICY` | `scored` | Paid unconditionally. The workload refuses to start on any other value. |
| `APP_ENV` | `production` | |
| `FIXTURE_BASE_URL` | the fixture's public hostname | Same as the app service. |
| `EVAL_SPLITS` | `dev,experimental` | Comma-separated, run in order. |
| `EVAL_ROUND` | `1` | Part of the result filename, and the way to ask for another round. |
| `EVAL_DRY_RUN` | `1` for the first start | See step 1 below. |

## Memory: two browsers on a 4 GB box

Scoring runs a second Chrome beside the public one. Measured, not assumed: the app
container reports its own RSS on `/healthz` (`browser.rss_mib`), **539.8 MiB** with the
browser connected and idle, against an M0 local peak of 794 MiB under load. The host has
3,723 MB total, ~477 MB of native Ubuntu and cloud agents, and 300–500 MB of k3s.

| Term | MB |
|---|---|
| Host total | 3,723 |
| Native + cloud agents | −477 |
| k3s + platform agent | −300 to −500 |
| App container (measured idle / expected peak) | −540 / −800 |
| Scored container (same image, same browser) | −540 / −800 |
| Fixture container (no browser) | −80 to −120 |
| **Remaining** | **~1,300 (idle) / ~800 (both peaking)** |

Both browsers recycle at 1,400 MiB RSS, which is the backstop rather than the plan. There
is also 1,987 MB of swap; the M0 pass condition was zero swap growth, so swap being touched
during a round is a finding, not a relief. Run one round at a time and do not score while a
load test is running.

**Config Editor, not an environment variable**: the billing key goes to `/etc/wf/gemini_paid_tier`,
outside `/data` for the same reason the free-tier key is — `/data` is the root the evidence store
serves from, and a secret does not live in a tree whose contents are handed out over HTTP.

## Step 1 — start it as a dry run. Always.

Set `EVAL_DRY_RUN=1` for the first start of the service, and after any change to its
configuration. The workload then runs everything that can fail before money is spent — the
credential policy, the billing key, the volume, the loopback server, the browser, the queue
— prices the round against the remaining daily allowance, prints the forecast, and submits
nothing.

It is not literally free: the server validates the credential with one minimal live call at
startup (A9.3), which is a fraction of a cent. That call is the point. A key that is present
but cannot call is found here rather than at case one of a scored round.

`EVAL_SPLITS=validation` also skips (held-out case files are not in the image), but it skips
for the wrong reason — the moment somebody mounts that file, the "dry run" spends. Use the
flag, which says what it means.

Clear `EVAL_DRY_RUN` and restart to score for real.

## The round is priced before the first case

The daily ceiling (`PROVIDER_SPEND_CEILING_USD_PER_DAY`, default $1.00) is enforced before
every provider call, and the ledger is shared with the public demo through the volume. Left
at that, a round that runs out of allowance stops mid-way and leaves a half-blocked result
file wearing the round's name — the ceiling would have destroyed a round and made it look
like a round.

So the workload forecasts first and refuses whole:

| Number | Where it comes from |
|---|---|
| Expected | cases × `EVAL_USD_PER_RUN` (measured: $0.0042, the most expensive dev case at `427cd96`; the mean was $0.0020) × `EVAL_COST_SAFETY_FACTOR` (1.5) |
| Worst case | cases × the per-run token budget priced out — $0.039 at the current budgets and prices |
| Remaining | today's ceiling minus today's spend, and the cumulative ceiling minus cumulative spend, whichever is smaller |

If the **expected** cost does not fit, the round is refused before case one, naming both
numbers. If the **worst case** does not fit, it warns and proceeds: refusing on the tail
would refuse nearly every round, since the tail is ~20× the measured cost. A 25-case round
is forecast at about **$0.16** and could in principle reach **$0.98**.

If a round does end early anyway, its result is written as `…-r<round>-degraded.json`, so
the clean name stays free and the same round number can be re-run.

The ceiling is per-process configuration while the spend ledger is shared state, so raising
`PROVIDER_SPEND_CEILING_USD_PER_DAY` **on this service only** gives the round headroom
without loosening anything on the public path.

## Running a round

Starting the service runs the round. It then idles with the browser shut down, so it is not holding
~600 MiB of Chromium between rounds; stopping the service entirely is also fine.

A restart **does not** re-run a split whose result file already exists. A platform restart is free
for the platform and not for us: an automatic restart loop would re-spend a paid split and overwrite
the result it was spent on. To score again, change `EVAL_ROUND` and restart — or set `EVAL_FORCE=1`
deliberately.

## Reading the results

The workload writes `<split>-deploy-<git_sha>-r<round>.json` into `/data/task1/eval-results` on the
shared volume, and the app service serves that directory read-only:

- `GET /api/eval-results` — one line per file: split, commit, finish time, and whether the file
  carries a degradation block.
- `GET /api/eval-results/<file>` — the report.

Held-out splits carry no per-case detail; the harness withholds it where the file is written, not
where it is served. Held-out case files are never in the image — they are mounted at score time.

## Failure modes it refuses rather than works around

- `CREDENTIAL_POLICY` is not `scored` → refuses to start, naming A9.6.
- No billing key at the configured path → refuses to start.
- The loopback server is not healthy inside the startup deadline → refuses, printing
  `unhealthy_because` rather than scoring a split against a half-started server.

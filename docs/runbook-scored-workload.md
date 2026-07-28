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
| Volume | **its own**, at `/data` | The platform will not attach an existing volume to a second service, so this cannot be the app's (A21.1). It is still required: without it the round's database and evidence are gone at the next restart. |
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

| Term | MB | Measured or estimated |
|---|---|---|
| Host total | 3,723 | **measured** (`free -m`) |
| Native + cloud agents | −477 | **measured** (M0, before k3s) |
| k3s + platform agent | −300 to −500 | *estimated* — never isolated on this host |
| App container (idle / peak) | −540 / −800 | **measured** (`/healthz` `browser.rss_mib`; M0 local peak) |
| Scored container (during a round) | −470 / −520 | **measured** — host `free -m` every 10 s across round r1: 1,795→2,266 MB at the round's start, peak 2,320 MB |
| Fixture container (no browser) | −80 to −120 | *estimated* |
| **Remaining** | **~1,400 measured at the round's peak** | host `avail` bottomed at 1,457 MB with both browsers up |

A17.13: the qualifier travels with the number. The ~800 MB worst case is acceptable, and a
reader can see that some of its inputs are estimates rather than readings.

Both browsers recycle at 1,400 MiB RSS, which is the backstop rather than the plan. There
is also 1,987 MB of swap; the M0 pass condition was zero swap growth, so swap being touched
during a round is a finding, not a relief. Run one round at a time and do not score while a
load test is running.

**Sample `free -m` every 10 s from 30 s before the restart to 5 minutes after the round.**
The pass condition is *zero swap growth*, and growth does not exist in a single reading.
Sampling beats three hand-taken points: the result file timestamps every case, so the split
boundaries can be cut out of the series afterwards, and a reading taken at the wrong moment
cannot be taken again. The five minutes after the round are the part that matters — whether
the memory comes back is the real A9.7 question, not what the peak was.

Round r1 measured this way: baseline 1,795 MB used, peak 2,320 MB, back to 1,836 MB within
a minute of the round finishing and flat for the next five. Swap held at 102 MB throughout —
no growth.

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

The ceilings are enforced before every provider call, **against billed dollars only**
(A23.1). The ledger records what a free-tier call would have cost as well, labelled as
notional; it is a price, not a charge, and enforcing against the sum of the two is how the
public demo came to be on course for a `provider_quota` after spending nothing.

**The ledger is in the store, the store is on the volume, and the volumes are separate — so
this service and the public demo count independently** (A21.7). Two ceilings of $1.00 would
be a system ceiling of $2.00, so they are not set per service: `SYSTEM_SPEND_CEILING_USD_PER_DAY`
($2.00) and `DEPLOYED_CEILING_SHARE` in `app/config.py` are one declaration, and each process
derives its own share from it (A22.3) — **scored $1.50, public app $0.50**. Above them sits
the cumulative development ceiling, **$8.00, a hard stop** (A23.4): the owner's real limit is
$10, and a ceiling exists to catch our own accounting being wrong, so it sits below the limit
it protects. The public path's cumulative allowance is **$0.00 until the A15 switchover
decides it** — grader traffic is outside this budget and must not be able to consume it.

Setting `PROVIDER_SPEND_CEILING_USD_PER_DAY` or `PROVIDER_SPEND_CEILING_USD` is refused at
startup rather than ignored. `/healthz` reports this process's ceilings, its billed and
notional spend separately, and the system total.

**Contention with the public demo is not a thing that can happen.** Under A12.2 the
public-serving container holds no billing credential, so it is structurally incapable of
writing a paid amount to any ledger; its $0.25 is a reservation for the A15 switchover, not
an allowance it is spending today. Every paid dollar in the accounting comes from this
workload. Nobody needs to "fix" a contention that the topology forbids.

Left at that, a round that runs out of allowance also stops mid-way and leaves a
half-blocked result file wearing the round's name — the ceiling would have destroyed a round
and made it look like a round.

So the workload forecasts first and refuses whole:

| Number | Where it comes from |
|---|---|
| Expected | cases × `EVAL_USD_PER_RUN` (measured: $0.0042, the most expensive dev case at `427cd96`; the mean was $0.0020) × `EVAL_COST_SAFETY_FACTOR` (1.5). Round r1 across 25 deployed cases came in at a mean of **$0.0019** and a maximum of **$0.0048** — the constant is the old maximum and the tail has since passed it, which is what the safety factor is for. |
| Worst case | cases × the per-run token budget priced out — $0.039 at the current budgets and prices |
| Remaining | today's ceiling minus today's spend, and the cumulative ceiling minus cumulative spend, whichever is smaller |

If the **expected** cost does not fit, the round is refused before case one, naming both
numbers. If the **worst case** does not fit, it warns and proceeds: refusing on the tail
would refuse nearly every round, since the tail is ~20× the measured cost. A 25-case round
is forecast at about **$0.16** and could in principle reach **$0.98**.

If a round does end early anyway, its result is written as `…-r<round>-degraded.json`, so
the clean name stays free and the same round number can be re-run.

Do not raise the ceiling to make a round fit (A20.5). The forecast gate is the control; the
ceiling is what catches the forecast being wrong, and raising it because a round approaches
it removes the only check on the forecast.

## Running a round

Starting the service runs the round. It then idles with the browser shut down, so it is not holding
~600 MiB of Chromium between rounds; stopping the service entirely is also fine.

A round is **locked to the build it started on** (A20.3): the commit is re-read at each
split boundary, and a round whose deployment changed underneath it is written under a
`-degraded` name with the reason inside the file. A split that started and never finished
leaves an `.inflight` marker under `eval-results/.rounds/`, and the next start refuses
rather than paying for that split a second time — read the log, then either change
`EVAL_ROUND` or set `EVAL_FORCE=1` having decided to pay again.

A round is identified by `EVAL_ROUND`, **not** by the commit. This platform redeploys on
every push to `master`, and the commit is part of the result's filename — so keying the
guard on the file alone would hold for restarts, which are free, and fail for a push, which
is the case that spends a whole round. The marker under `eval-results/.rounds/` is what the
skip decision reads.

A restart or a redeploy **does not** re-run a split whose round has already been scored. A platform restart is free
for the platform and not for us: an automatic restart loop would re-spend a paid split and overwrite
the result it was spent on. To score again, change `EVAL_ROUND` and restart — or set `EVAL_FORCE=1`
deliberately.

## Getting the results out — this is part of running the round (A21.2)

The workload writes `<split>-deploy-<git_sha>-r<round>.json` into `/data/task1/eval-results` on **its
own** volume. Nothing else can read that volume. A paid round that stays there exists in one place,
on a disk whose contents are one console click from gone.

From the host, k3s keeps volume contents on the local filesystem:

```bash
sudo find /var/lib/rancher/k3s/storage -path '*task1/eval-results/*.json' -newermt '-1 day'
```

Copy the round's file into `eval/results/` and commit it, like every other measurement in this
project. It is then served publicly from the image:

- `GET /api/eval-results` — one line per file: split, commit, finish time, `source`
  (`repository` or `volume`), and whether the file carries a degradation block.
- `GET /api/eval-results/<file>` — the report. The repository's copy resolves first.

Held-out splits carry no per-case detail; the harness withholds it where the file is written, not
where it is served. Held-out case files are never in the image — they are mounted at score time.

### The evidence comes out too (A22.7)

After each split the workload writes `bundles/<split>-<sha>-r<round>/` next to the result
file, containing:

- the **complete bundle for every run the round did not settle** — one that failed on its
  own terms, and one the product called a success while the independent check disagreed
  (A24.8). These are the ones a reader has reason to doubt, and the fewest. Carrying on the
  run's own verdict alone is what withheld r1's four most interesting bundles;
- the bundle for the **success sample named in `eval/bundle-sample.json`**, which is
  committed before the round so the sample cannot be chosen to flatter it;
- `manifest.json`: what was carried, what was omitted and why, with the per-case
  verification record and artifact hashes for everything omitted (A11.8).

Copy that directory into `eval/results/bundles/` and commit it with the result file. The app
serves it at `GET /api/eval-bundles` and `GET /api/eval-bundles/<round>/<case>/<file>`, so
the public frontend reaches the evidence and the scored service is never reachable.

Since A24.6 each captured DOM is accompanied by an `aria:` artifact — the accessibility
tree, which is what an F1 locator's role and name are read from. Measured on the fixture it
adds **22–32%** to the stored bytes of a capture (959–1,638 B against 3.3–7.4 KB of DOM);
r1's dev split used 5.95 MiB of a 48 MiB cap, so the cap is not what decides this.

The cap is `EVAL_BUNDLE_CAP_MIB` (48 MiB per round). Every candidate is **weighed from the
store** before the cap is applied, so anything listed as `over the size cap` is a measured
omission rather than a guess — and that residue, not the whole category, is what A21.4's
limitation is written against.

## Failure modes it refuses rather than works around

- `CREDENTIAL_POLICY` is not `scored` → refuses to start, naming A9.6.
- No billing key at the configured path → refuses to start.
- The loopback server is not healthy inside the startup deadline → refuses, printing
  `unhealthy_because` rather than scoring a split against a half-started server.

**A refusal holds the container; it does not exit.** Exiting non-zero is what a program
should do and the wrong thing here: the platform restarts a failed container on a backoff,
so a refusal turns into a crash loop whose only visible symptom is

```
[Zeabur] Pod/… - BackOff: Back-off restarting failed container …
```

— a message about restarting that never names what was wrong, while the reason scrolls out
of the log. So the workload prints the reason, stays up, and repeats the reason every 15
minutes. **If the service shows as running, read the log before assuming it scored**: a held
container and a finished round look the same from the outside and say different things at
the bottom of their logs. Unexpected crashes are held the same way, with the traceback.

Run from a terminal with `--no-idle`, a refusal is still a non-zero exit — there is no
backoff loop to defend against and a shell wants the status code.

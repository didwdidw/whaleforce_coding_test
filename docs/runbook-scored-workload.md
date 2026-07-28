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

**Config Editor, not an environment variable**: the billing key goes to `/etc/wf/gemini_paid_tier`,
outside `/data` for the same reason the free-tier key is — `/data` is the root the evidence store
serves from, and a secret does not live in a tree whose contents are handed out over HTTP.

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

# M1 Deployment Runbook — Zeabur, two services

**Repo:** `git@github.com:didwdidw/whaleforce_coding_test.git`, branch `master`, pushed.
**Host:** `43.166.128.37` (Tencent / Ashburn, A9.10), SSH alias `wf-prod`.

Two services in one Zeabur project, both built from the same `Dockerfile` in this repo and
distinguished only by `APP_ROLE`. Each gets its own generated `*.zeabur.app` domain.

**Why two services rather than one with two ports.** The fixture must be reachable over its
own public hostname (S-2.8). The egress guard refuses private and loopback destinations, and
the tempting fix — an allow-list hole for the fixture — would make the SSRF claim untrue.
Two hostnames means no exemption exists to be argued about. This is now demonstrated rather
than asserted: running the app under production config against a `127.0.0.1` fixture returns
`blocked / policy_refused`, which is the correct and useful failure.

## If Zeabur says the Dockerfile is required

> `INVALID_ARGUMENT — Dockerfile is required for arbitrary Git sources. Auto-detection is
> not supported yet.`

This is Zeabur telling you the repo was added as a **raw Git URL** rather than through the
GitHub integration. In that mode `zbpack` does not inspect the repo, so it will not find the
root `Dockerfile` by itself.

**Preferred fix — connect the repo through GitHub instead.** In the service's source
settings choose GitHub and pick `didwdidw/whaleforce_coding_test`, authorising the Zeabur
GitHub App for the private repo. That removes the limitation entirely and gives auto-deploy
on push, which you want anyway.

**If you would rather keep the raw Git URL**, `zbpack.json` is now committed at the repo
root and declares the path explicitly:

```json
{ "dockerfile": { "path": "Dockerfile" } }
```

Redeploy and it should build. If it still does not, set `ZBPACK_DOCKERFILE_PATH=Dockerfile`
as an environment variable on each service — same instruction, delivered through the
dashboard instead of the repo.

Both services share this one Dockerfile; they differ only by `APP_ROLE`. Note that Zeabur
also matches `<service-name>.Dockerfile` automatically, so **do not name your services
`app` or `fixture` and then add files with those names** unless you intend to split the
build in two.

## Pre-deploy validation — already run, passing

`deploy/m1-build-check.yaml` runs every step the Dockerfile performs after `FROM`, inside a
k3s pod on the production host, so a build mistake is found here rather than in a remote
Zeabur build log. Result on the current commit: **ALL CHECKS PASSED**.

| Step | Result |
|---|---|
| `pip install -r requirements.txt` | ok |
| Chromium launch check | ok — 149.0.7827.55 |
| `import app.server, fixture.server` | ok |
| Test suite | 32 passed |
| Startup refuses `ALLOW_PRIVATE_EGRESS` in production | ok |
| `entrypoint.sh` with `APP_ROLE=app` serves `/healthz` | ok — guard on, browser generation 1 |
| `entrypoint.sh` with `APP_ROLE=fixture` | ok — `/healthz` 200, `GET /search` **405** |

It caught one defect that would otherwise have shipped: `requirements.txt` was missing
`fastapi`, `uvicorn`, `jinja2` and `python-multipart` — installed into the development venv
and never pinned. The image would have **built successfully** and then crashed on start with
`ModuleNotFoundError`. Now pinned.

To re-run after a change:

```bash
rsync -aq --exclude='.git/' --exclude='.venv/' --exclude='api_keys/' \
  --exclude='preflight/results/' --exclude='task_description/' ./ wf-prod:~/build-check/
rsync -aq deploy/ wf-prod:~/deploy/
ssh wf-prod 'sudo k3s kubectl delete pod m1-build-check --ignore-not-found; \
  sudo k3s kubectl apply -f ~/deploy/m1-build-check.yaml'
ssh wf-prod 'sudo k3s kubectl logs -f m1-build-check'
```

---

## Service 1 — `fixture`

| Setting | Value |
|---|---|
| Source | this GitHub repo, branch `master` |
| Build | Dockerfile (root) — **do not let Zeabur auto-detect Python**, a stock image has no Chromium |
| `APP_ROLE` | `fixture` |
| `APP_ENV` | `production` |
| `GIT_SHA` (build arg, optional) | the deployed commit — see below |
| Domain | Generate Domain → note it, e.g. `wf-fixture.zeabur.app` |

The fixture serves no browser itself; it is a plain FastAPI app. Deploy it **first** — the
app needs its hostname.

Verify:

```bash
curl -s https://<fixture-domain>/healthz
curl -s -o /dev/null -w '%{http_code}\n' https://<fixture-domain>/search      # expect 405
curl -s -o /dev/null -w '%{http_code}\n' -X POST -d q=lantern https://<fixture-domain>/search  # 200
curl -s https://<fixture-domain>/__testhook__/selftest | head -c 200          # "ok": true
```

The 405 matters: GET on `/search` is refused by design, which is what makes GS-1
shortcut-proof. If it returns 200, the wrong thing is deployed.

## Service 2 — `app`

| Setting | Value |
|---|---|
| Source | same repo, same branch |
| Build | Dockerfile (root) |
| `APP_ROLE` | `app` |
| `APP_ENV` | `production` |
| `FIXTURE_BASE_URL` | `https://<fixture-domain>` — **https, and the public name** |
| `ALLOW_PRIVATE_EGRESS` | **do not set** |
| Domain | Generate Domain, e.g. `wf-agent.zeabur.app` |

### The volume is not optional, and it must exist before this service starts (A11.1)

**Attach a persistent volume to the `app` service and mount it at `/data`.** Do this
*before* deploying the release that carries Amendment 11, because the app now refuses to
start without it. That is deliberate: the alternative is writing evidence to the container
filesystem, which works, looks correct, and deletes every artifact on the next deploy.

The store makes two checks at startup, and both have to pass:

1. **A write probe** — it writes, reads back, and deletes a marker. A path-existence check
   passes on an unmounted directory, a read-only mount and a full disk alike.
2. **A mount check** — the data directory's device id must differ from `/`. The image
   creates `/data` itself, so without this the probe would happily succeed on ephemeral
   storage. This is the check that catches "the volume was never attached".

`DATA_DIR` is **not** set in the image; the default `/data/task1` lives in `app/config.py`.
Set `DATA_DIR` only to override it. `REQUIRE_PERSISTENT_STORE=false` switches off check 2
and belongs in local development only — setting it in production reintroduces exactly the
silent data loss the volume was mounted to prevent.

**The accepted cost (A11.2):** Zeabur switches a volume-mounted service from
`RollingUpdate` to `Recreate`, so each deploy now takes a full cold start of downtime
(~8 s measured, M1 report §4.1) instead of the overlapping rollout. This is paid during
development and repaid during grading, and it must be stated in the analysis report rather
than presented as free.

**Build provenance.** `.dockerignore` excludes `.git`, so the commit is baked in as the
`GIT_SHA` build argument. If Zeabur exposes the commit as `ZEABUR_GIT_COMMIT_SHA` at
runtime the app picks that up automatically; otherwise pass `--build-arg GIT_SHA=...` or set
`GIT_SHA` as a service environment variable. `/healthz` reports what it resolved. A run that
reports `unknown` is not reportable under S-10.7 — the field is deliberately honest rather
than guessed, so check it after the first deploy.

**`ALLOW_PRIVATE_EGRESS` cannot be set here.** The app refuses to start if it is enabled
while `APP_ENV` is anything other than a development value, and prints why. An unset or
misspelled `APP_ENV` is treated as production, so the unsafe combination cannot be reached
by a typo.

## Post-deploy checks

```bash
APP=https://<app-domain>

# 1. Alive, and the guard is on.
curl -s $APP/healthz | python3 -m json.tool | grep -A4 egress_guard

# 2. Pre-executed runs exist, including a refusal (S-11.5).
curl -s $APP/ | grep -c 'runs/run_'

# 3. Every one of those runs opens. This is the page all the inspectability claims point
#    at, and it 500'd for three days without any other check noticing.
for id in $(curl -s $APP/ | grep -o 'runs/run_[0-9a-f]*' | sort -u); do
  curl -s -o /dev/null -w "%{http_code} $id\n" $APP/$id
done

# 4. Queue refuses rather than queues without bound (S-11.8).
for i in $(seq 1 8); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST \
    -d 'task=Search the fixture catalogue for lantern' $APP/api/runs &
done; wait; echo

# 5. Retry-After is present on a genuine 429.
curl -s -D - -o /dev/null -X POST -d 'task=Browse the fixture catalogue' $APP/api/runs \
  | grep -iE '^(HTTP/|retry-after)'

# 6. Out-of-scope task refuses before any browsing.
curl -s -X POST -d 'task=Log into my brokerage account' $APP/api/runs
```

Expect from (3): `200` on every line, with no line missing — the pre-executed set spans
several terminal statuses and a template can break on one and not the others. From (4): a
few `202` then `429`. From (6): `unsupported / policy_refused` with no navigation in the
trace.

**Cold start (A8.5) — measured, see the M1 report §4 for the numbers.** Timing a single
request after a deploy is not enough: it reports whichever pod happened to answer. Drive the
restart and watch the window instead.

```bash
NS=environment-6a6644a75f062718bc7b1a95
POD=$(ssh wf-prod "sudo kubectl -n $NS get pods -o name | grep 6a664945")

# Poll the public URL continuously in one shell...
while :; do
  printf '%s ' "$(date +%s.%N)"
  curl -s -o /dev/null -m 4 -w '%{http_code} %{time_total}\n' https://wf-agent.zeabur.app/
  sleep 0.4
done

# ...and delete the pod in another. The gap between the last 200 and the next one is the
# window a grader can land in.
ssh wf-prod "sudo kubectl -n $NS delete $POD --wait=false"

# kubelet reports the pull itself, which the poll cannot see:
ssh wf-prod "sudo kubectl -n $NS get events --sort-by=.lastTimestamp | grep -E 'Pulled|Started'"
```

Two figures come out of this and they answer different questions: **pod restart with the
image on the node** is the routine case, and **a full redeploy including the pull** is the
window a pushed version is exposed to. Check `/healthz` at the first `200` as well — if
`browser.connected` is false there, the homepage is answering before the system can actually
run anything, and the real cold start is longer than the HTTP number suggests.

## Persistence checks after a deploy (A-29, A-30, A-31)

```bash
APP=https://wf-agent.zeabur.app

# A-31: the store reports its own state, and health fails if it is not usable.
curl -s $APP/healthz | python3 -c 'import json,sys; d=json.load(sys.stdin)["storage"]; \
  print({k: d[k] for k in ("data_dir","writable","on_mounted_volume","persistent",
                           "artifacts_pinned","fraction_of_ceiling")})'

# A-29: note a run id now, redeploy, then confirm its artifact still resolves.
curl -s $APP/api/runs/<run-id> | python3 -c 'import json,sys; \
  print([(a["artifact_id"], a["state"]) for a in json.load(sys.stdin)["artifacts"]])'
curl -s -o /dev/null -w "%{http_code}\n" $APP/api/artifacts/<artifact-id>   # expect 200

# A-30: an expired artifact answers 410 with its metadata and a date, never 404.
curl -s $APP/api/artifacts/<expired-id> | python3 -m json.tool | head -14
```

Expect from A-30: `state: expired`, `expired_on` set, and `source_url`, `retrieved_on`,
`sha256` and `length` all still present. The run page shows **expired on `<date>`** with the
hash retained, not an empty panel. The homepage demonstrations are pinned and never expire;
each shows the date its evidence was captured, so a two-week-old demonstration reads as
dated rather than current.

## Capacity this deployment has to fit in — measured, not estimated

`deploy/m0-ram-measure.yaml` has already run in a pod on this host (M0 report §1.1):

| Term | MiB |
|---|---|
| MemTotal | 3,723.9 |
| ZeaburOS + k3s + Tencent agents, before we start | 1,507.8 |
| App at peak (browser + 2 contexts) | 996.7 |
| **Spare** | **1,219.4** — 67% of the box used at peak |

Swap was untouched. The browser recycles at an app-tree ceiling of 1,400 MiB, which sits
above the measured peak with room to spare and still leaves the box at 78% if it is reached.

Two consequences for the Zeabur service settings: **do not set a memory limit below ~1.5 GB**
on the app service, and expect the fixture service to be small — it runs no browser.

## If the build fails

The most likely cause is Zeabur choosing its Python auto-detection over the Dockerfile. The
image must be `mcr.microsoft.com/playwright/python:v1.61.0-noble`; a stock Python image
builds fine and then fails at the first browser launch. The Dockerfile ends with a Chromium
launch check precisely so that failure happens at build time, not on a grader's first click.

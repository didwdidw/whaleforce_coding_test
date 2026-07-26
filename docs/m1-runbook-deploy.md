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

---

## Service 1 — `fixture`

| Setting | Value |
|---|---|
| Source | this GitHub repo, branch `master` |
| Build | Dockerfile (root) — **do not let Zeabur auto-detect Python**, a stock image has no Chromium |
| `APP_ROLE` | `fixture` |
| `APP_ENV` | `production` |
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

Optionally add a volume mounted at `/data` so runs and artifacts survive a redeploy.
Without it the store starts empty on each release — acceptable, but it should be a decision.

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

# 3. Queue refuses rather than queues without bound (S-11.8).
for i in $(seq 1 8); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST \
    -d 'task=Search the fixture catalogue for lantern' $APP/api/runs &
done; wait; echo

# 4. Retry-After is present on a genuine 429.
curl -s -D - -o /dev/null -X POST -d 'task=Browse the fixture catalogue' $APP/api/runs \
  | grep -iE '^(HTTP/|retry-after)'

# 5. Out-of-scope task refuses before any browsing.
curl -s -X POST -d 'task=Log into my brokerage account' $APP/api/runs
```

Expect from (3): a few `202` then `429`. From (5): `unsupported / policy_refused` with no
navigation in the trace.

**Cold start (A8.5) is measured here**, on the first request after a deploy:

```bash
time curl -s -o /dev/null https://<app-domain>/
```

Record it — this is the figure M0 deferred, and it is the one a grader experiences.

## Pod re-verification of RAM (the other M0 deferral)

Once Zeabur has provisioned k3s on the box, `deploy/m0-ram-measure.yaml` runs the same
measurement inside a pod and turns the estimated 300–500 MB k3s term into a measured one.
On the host, via `ssh wf-prod`:

```bash
sudo k3s kubectl get nodes -o wide          # confirm k3s is now present
free -m                                     # the new baseline, with k3s running
```

If `free -m` shows the used figure has moved from ~477 MB to somewhere near 800–1,000 MB,
that is the k3s term arriving and the headroom table in the M0 report should be updated with
the measured value.

## If the build fails

The most likely cause is Zeabur choosing its Python auto-detection over the Dockerfile. The
image must be `mcr.microsoft.com/playwright/python:v1.61.0-noble`; a stock Python image
builds fine and then fails at the first browser launch. The Dockerfile ends with a Chromium
launch check precisely so that failure happens at build time, not on a grader's first click.

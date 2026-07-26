# M0.1 Runbook — RAM under load, on the host

**Host:** `ubuntu@43.166.128.37` (Tencent / Ashburn, A9.10). **Prerequisite: M0.2 passed** — it did
(`server_environment.txt`).

Closes the last M0 gate (§13(a)). **A8.5 cold start is not measured here** — it moves to M1, because
the runtime is the one thing that genuinely changes it.

**Measured on the host with system Python, not in a container.** The box has no container runtime of
any kind, and none is being installed by hand: Zeabur brings k3s when it deploys, and a manual copy
risks colliding with it. Container-vs-host RSS differs by tens of MB, which does not change whether
the app fits. The same measurement is **re-verified in a pod after M1 deploys**
(`deploy/m0-ram-measure.yaml`), and both figures stay in the report.

**"Pass" is two conditions:**

1. App peak RSS fits, with the corrected headroom arithmetic below.
2. **Swap did not grow.** The box has 1,987 MB of swap, so it will not OOM at the peak — it will get
   slow, and a slow run inside the 180 s wall clock (S-6.1) fails as `timeout`, a symptom two steps
   from its cause. A green peak reached by swapping is a **fail**.

---

## Step 1 — from your Mac

```bash
cd /Users/tim/Desktop/whaleforce_coding_test
rsync -av --exclude='results/' --exclude='dist/' --exclude='__pycache__/' \
  preflight/ ubuntu@43.166.128.37:~/preflight/
```

## Step 2 — on the server, one paste

```bash
bash ~/preflight/run_host_ram.sh
```

It prints the pre-launch baseline and its largest contributors, creates `~/.venv-preflight`, installs
`playwright` plus Chromium's shared libraries via apt, runs the measurement with both contexts loaded
for 20 s, and prints the verdict. Result lands in `~/cloud-ram.json`.

`sudo` is used twice: `apt-get install python3-venv` and `playwright install-deps chromium`. Nothing
else on the host is touched and no provider API is called.

## Step 3 — send back

```bash
cat ~/cloud-ram.json
```

Plus the printed output from Step 2.

---

## Headroom arithmetic — corrected

The 477 MB measured at idle is **native Ubuntu plus Tencent's own agents** (`tat_agent`,
`barad_agent`, `YDService`/`YDLive`). It contains **no k3s** — Zeabur has not touched the box yet, so
this is the floor, not the deployed baseline.

| Term | MB | Status |
|---|---|---|
| Total | 3,723 | measured |
| − native Ubuntu + Tencent agents | −477 | measured |
| − k3s + Zeabur agent | −300 to −500 | **estimated; confirmed at the M1 pod re-verification** |
| − app peak | −~800 | measuring now |
| **= remaining** | **~1,950–2,150** | |

## What I expect, so a surprise reads as a surprise

| Measure | Expectation | Basis |
|---|---|---|
| App tree peak RSS | 550–800 MiB (Linux usually below macOS) | local baseline 794 MiB, report §1 |
| Chromium share | ~60–75% of peak | 601 of 794 MiB locally |
| Playwright `node` driver | ~120–160 MiB | 155 MiB locally |
| **Swap growth** | **0 — anything else is a fail** | pass condition above |
| Concurrent load of both pages | under 1 s | 0.05–0.098 s per page from this IP, report §2 |

Above ~1.2 GB peak, or any swap growth, is a finding and I stop rather than tune it away. Cutting
concurrency or budgets to fit the box is what the M0 brief and A7.8.3 prohibit — it would silently
change the system being measured.

## Deferred to M1

`deploy/m0-ram-measure.yaml` and `deploy/m0-coldstart.yaml` re-run this inside k3s once Zeabur has
provisioned it. That run fixes the 300–500 MB k3s term as a measured number and produces the A8.5
cold-start figure. Note for then: a container's default `/dev/shm` is 64 MB and Chromium crashes
without more — `measure_ram.py` passes `--disable-dev-shm-usage`, so production must pass the same
flag or mount a larger `/dev/shm`, or it passes every measurement and dies under real load.

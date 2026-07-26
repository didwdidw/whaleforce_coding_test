# M0.1 Runbook — RAM and cold start, measured inside k3s

**Host:** `43.166.128.37` (Tencent / Ashburn, A9.10). **Prerequisite: M0.2 passed** — it did,
all clear (`server_environment.txt`).

This closes the last M0 gate (§13(a)) and the A8.5 cold-start figure.

**No Docker, and no image build.** The box already runs k3s, and installing a second container
runtime is a decision rather than a step. Running the measurement as a k3s pod is not a workaround —
it is **closer to production than Docker would have been**, because Zeabur deploys onto this same k3s
and that is the runtime that will actually serve the system. The measurement also needs only
`playwright`, which the official Playwright image already ships, so nothing has to be built first.

`Dockerfile` stays in the repo: Zeabur builds it on their side at deploy time. It is not needed here.

**"Pass" is two conditions, not one:**

1. App peak RSS plus the ~477 MB orchestration baseline fits in 3,723 MB with room to grow.
2. **Swap did not grow.** The box has 1,987 MB of swap, so it will not OOM at the peak — it will get
   slow, and a slow run inside the 180 s wall clock (S-6.1) fails as `timeout`, a symptom two steps
   from its cause. `measure_ram.py` returns an explicit swap verdict. **A green peak reached by
   swapping is a fail.**

---

## Step 1 — send the files (from your Mac)

```bash
cd /Users/tim/Desktop/whaleforce_coding_test
rsync -av --exclude='results/' --exclude='dist/' --exclude='__pycache__/' \
  preflight/ SSH_USER@43.166.128.37:~/preflight/
rsync -av deploy/ SSH_USER@43.166.128.37:~/deploy/
```

`api_keys/` is not in the transfer and is not needed — nothing here calls a provider.

## Step 2 — confirm k3s and pick the kubectl form

```bash
sudo k3s --version
sudo k3s kubectl get nodes -o wide
sudo k3s kubectl get pods -A --no-headers | wc -l
```

Every command below uses `sudo k3s kubectl`. If a plain `kubectl` is on PATH and already points at
this cluster, that works too.

The pod mounts `/home/ubuntu/preflight` from the host, so confirm that is where Step 1 landed:

```bash
ls ~/preflight/measure_ram.py && echo "path ok: $(realpath ~/preflight)"
```

If your home is not `/home/ubuntu`, edit `hostPath.path` in `deploy/m0-ram-measure.yaml` to match —
the manifest cannot expand `~`.

## Step 3 — pull the image first, and time it separately

The pull is a one-time cost and would otherwise contaminate the cold-start figure.

```bash
time sudo k3s ctr images pull mcr.microsoft.com/playwright/python:v1.61.0-noble
sudo k3s ctr images ls | grep playwright
```

Expect a few minutes and roughly 2 GB. Report the time — it is the deploy-day cost, distinct from the
per-start cost measured in Step 5.

## Step 4 — the RAM measurement

```bash
sudo k3s kubectl delete pod m0-ram-measure --ignore-not-found
sudo k3s kubectl apply -f ~/deploy/m0-ram-measure.yaml
sudo k3s kubectl wait --for=condition=Ready pod/m0-ram-measure --timeout=180s
sudo k3s kubectl logs -f m0-ram-measure | tee ~/cloud-ram.json
```

The pod runs `hostPID: true` so `ps` can see the host's processes — without it the k3s and Zeabur
agent baseline would read as zero and the app would look better than it is. It sets **no memory
limit**, because a limit would either cap the peak we came to measure or OOM-kill the pod mid-run.

If the pod does not become Ready, get the reason rather than retrying:

```bash
sudo k3s kubectl describe pod m0-ram-measure | tail -30
```

## Step 5 — cold start (A8.5)

Run this **after** Step 3, so the image is warm and the figure is a per-start cost, not a pull.

```bash
for i in 1 2 3; do
  sudo k3s kubectl delete pod m0-coldstart --ignore-not-found >/dev/null
  START=$(date +%s.%N)
  sudo k3s kubectl apply -f ~/deploy/m0-coldstart.yaml >/dev/null
  sudo k3s kubectl wait --for=condition=Ready pod/m0-coldstart --timeout=120s >/dev/null 2>&1
  sudo k3s kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/m0-coldstart --timeout=120s >/dev/null
  END=$(date +%s.%N)
  echo "run $i: wall $(echo "$END - $START" | bc)s | $(sudo k3s kubectl logs m0-coldstart)"
done
sudo k3s kubectl delete pod m0-coldstart --ignore-not-found
```

Each line gives two numbers: the **wall time** a user would wait (scheduling + container start +
work) and, from the pod's own output, `browser_launch_s` and `first_page_loaded_s` measured from
inside. A grader experiences the first; the second tells us which part to attack if it is slow.

## Step 6 — read the verdict

```bash
python3 - <<'PY'
import json, os
d = json.load(open(os.path.expanduser('~/cloud-ram.json')))
o = d["orchestration_baseline"]
print("orchestration baseline (k3s + agent, before we launch):",
      o["system_used_mib_before_launch"], "MiB")
print("largest processes outside our tree:",
      [(x["comm"], x["rss_mib"]) for x in o["outside_our_tree"]["top"][:6]])
print()
print("app tree marks (MiB):", json.dumps(d["marks_mib"], indent=1))
print("app tree PEAK:", d["app_tree_peak_rss_mib"], "MiB")
print("by process at peak:", d["peak_by_process_mib"])
print()
print("SWAP:", json.dumps(d["swap"], indent=1))
print("host meminfo:", json.dumps(d["platform_meminfo"], indent=1))
print("load errors:", d["load_errors"])
PY
```

Paste back `~/cloud-ram.json`, the three cold-start lines, and the Step 3 pull time.

## Cleanup

```bash
sudo k3s kubectl delete pod m0-ram-measure m0-coldstart --ignore-not-found
```

The image stays in containerd — production wants it there anyway.

---

## What I expect, so a surprise is visible as a surprise

| Measure | Expectation | Basis |
|---|---|---|
| App tree peak RSS | 550–800 MiB (Linux usually below macOS) | local baseline 794 MiB, report §1 |
| Chromium share | ~60–75% of the peak | 601 of 794 MiB locally |
| Playwright `node` driver | ~120–160 MiB | 155 MiB locally |
| **Swap growth** | **0 — anything else is a fail** | pass condition above |
| Orchestration baseline | ~477 MB | measured at idle, report §2 |
| Headroom after app + baseline | ~2.4 GB of 3,723 MB | 3,723 − 477 − ~800 |
| Browser launch (in-pod) | 0.5–2 s | — |
| First page loaded (in-pod) | under 3 s | books.toscrape was 0.098 s from this IP |
| Pod wall time, warm image | 3–15 s | includes k3s scheduling |
| Image pull, one time | minutes, ~2 GB | — |

If the peak lands materially above ~1.2 GB, or swap grows at all, that is a finding and I stop rather
than tune it away. Cutting concurrency or budgets to fit the box is exactly what the M0 brief and
A7.8.3 prohibit — it would silently change the system being measured.

## One thing this measurement fixes for production

The `/dev/shm` default in a container is 64 MB, and Chromium crashes without more.
`measure_ram.py` passes `--disable-dev-shm-usage`, so **production must pass the same flag** or mount
a larger `/dev/shm`. `deploy/m0-ram-measure.yaml` carries the `emptyDir` alternative commented out, so
both options stay visible rather than one being silently assumed. Getting this wrong produces a
container that passes every measurement here and dies under real load.

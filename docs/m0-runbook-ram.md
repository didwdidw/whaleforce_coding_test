# M0.1 Runbook — RAM and cold start, inside the deployment image

**Host:** `43.166.128.37` (Tencent / Ashburn, A9.10). **Prerequisite: M0.2 passed** — it did,
all clear, `server_environment.txt`.

This closes the last M0 gate (§13(a)) and the A8.5 cold-start figure. It runs **inside the
Playwright-based deployment image**, not against the system Python: a number measured against a
different runtime than production uses does not describe production.

**What "pass" means here — two conditions, not one:**

1. App peak RSS + the ~477 MB orchestration baseline fits in 3,723 MB with room for growth.
2. **The run did not touch swap.** The box has 1,987 MB of swap enabled, so it will not OOM at the
   peak — it will get slow, and a slow run inside the 180 s wall clock (S-6.1) fails as `timeout`,
   a symptom two steps from its cause. `measure_ram.py` now reports a swap verdict for exactly this;
   a green peak reached by swapping is a **fail**.

---

## Step 1 — get the files onto the box (from your Mac)

`Dockerfile` and `requirements.txt` are new, so send those too. `api_keys/` is not in the transfer
and is not needed — nothing here calls a provider.

```bash
cd /Users/tim/Desktop/whaleforce_coding_test
rsync -av --exclude='results/' --exclude='dist/' --exclude='__pycache__/' \
  preflight/ SSH_USER@43.166.128.37:~/preflight/
rsync -av Dockerfile requirements.txt SSH_USER@43.166.128.37:~/
```

## Step 2 — confirm Docker is available

```bash
docker version --format '{{.Server.Version}}' 2>/dev/null || sudo docker version --format '{{.Server.Version}}'
```

If Docker is not installed, say so rather than installing something — the box is managed by Zeabur
and k3s is already running on it, so adding a second container runtime is a decision, not a step.
The fallback is to run the measurement inside the k3s node instead, which I'll write up if needed.

## Step 3 — build the deployment image (timed)

The build is also the first half of the cold-start answer: how long a cold deploy takes before the
app can serve anything.

```bash
cd ~ && time docker build -t task1-agent:m0 .
```

The build ends with a Chromium launch check, so a base image that no longer ships the browser fails
the build rather than the first run.

## Step 4 — cold start inside the image (A8.5)

Container start → browser up → first page loaded, measured three times so the figure is not a single
sample:

```bash
for i in 1 2 3; do
  docker run --rm -v ~/preflight:/app/preflight task1-agent:m0 \
    python - <<'PY'
import asyncio, json, time
from playwright.async_api import async_playwright
async def main():
    t0 = time.time(); m = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--disable-dev-shm-usage"])
        m["browser_launch_s"] = round(time.time() - t0, 2)
        pg = await (await b.new_context()).new_page()
        await pg.goto("https://books.toscrape.com/", wait_until="load", timeout=60000)
        m["first_page_loaded_s"] = round(time.time() - t0, 2)
        await b.close()
    print(json.dumps(m))
asyncio.run(main())
PY
done
```

Note this excludes container scheduling time. For the number a grader actually experiences, time the
whole invocation: `time docker run --rm task1-agent:m0 python -c "pass"` gives the container-start
floor to add on top.

## Step 5 — the RAM measurement

```bash
docker run --rm \
  -v ~/preflight:/app/preflight \
  -v ~/results:/out \
  task1-agent:m0 \
  python preflight/measure_ram.py --hold 20 --out /out/cloud-ram.json
```

`--hold 20` keeps both contexts loaded for 20 s so the sampler sees a steady state rather than only
the load spike.

**Two caveats about what this measures.** The container sees the host's `/proc/meminfo`, so the
system-used and swap figures are the **host's**, which is what we want — the orchestration baseline
and swap pressure are host properties. But `--disable-dev-shm-usage` is set because Docker's default
`/dev/shm` is 64 MB and Chromium will crash without it; production must set the same flag or raise
`--shm-size`, or the container works here and dies under real load.

## Step 6 — read the verdict

```bash
python3 - <<'PY'
import json
d = json.load(open('/root/results/cloud-ram.json'.replace('/root', __import__('os').path.expanduser('~'))))
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
print("swap:", json.dumps(d["swap"], indent=1))
print("host meminfo:", json.dumps(d["platform_meminfo"], indent=1))
print("load errors:", d["load_errors"])
PY
```

Then paste back `cloud-ram.json`, the three cold-start lines, and the `docker build` time.

## What I expect, so a surprise is visible as a surprise

| Measure | Expectation | Source |
|---|---|---|
| App tree peak RSS | 550–800 MiB (Linux usually below macOS) | local baseline 794 MiB, report §1 |
| Chromium share of that | ~60–75% | 601 of 794 MiB locally |
| Playwright `node` driver | ~120–160 MiB | 155 MiB locally |
| Swap growth | **0** | must be, per the pass condition above |
| Headroom after app + baseline | ~2.4 GB of 3,723 MB | 3,723 − 477 − ~800 |
| Browser launch | 0.5–2 s warm image | — |
| First page loaded | under 3 s (books.toscrape was 0.098 s over the network) | report §2 |
| `docker build` first time | several minutes, mostly base image pull | — |

If the peak lands materially above ~1.2 GB, or swap grows at all, that is a finding and I stop rather
than tune it away — the concurrency and budget numbers are the system being measured, and shrinking
them to fit the box is exactly what A7.8.3 and the M0 brief prohibit.

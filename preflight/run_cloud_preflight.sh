#!/usr/bin/env bash
# M0 gates (a), (b), (c) and the A8.5 cold-start figure, measured from the deployment box.
#
# Run this on a real cloud container or VM with 1-2 GB of RAM. A home network always comes
# back green, which just moves the discovery to deployment day.
#
#   docker run --rm -m 2g -v "$PWD:/w" -w /w python:3.12-slim bash preflight/run_cloud_preflight.sh
#
# On a bare VM: apt-get install -y python3 python3-venv, then bash preflight/run_cloud_preflight.sh
#
# Writes preflight/results/cloud-*.json. Paste those files back; they contain no secrets
# and make no provider API calls.
set -u

OUT=preflight/results
mkdir -p "$OUT"
START=$(date +%s)

echo "=== host ==="
{
  echo "date_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "kernel=$(uname -srm)"
  echo "nproc=$(nproc 2>/dev/null || echo unknown)"
  grep -E '^(MemTotal|MemAvailable|SwapTotal)' /proc/meminfo 2>/dev/null
  for f in /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory/memory.limit_in_bytes; do
    [ -r "$f" ] && echo "cgroup_limit=$(cat $f) ($f)"
  done
} | tee "$OUT/cloud-host.txt"

echo
echo "=== installing dependencies (timed: this is the cold-start floor) ==="
DEP_START=$(date +%s)
if [ ! -d .venv-preflight ]; then
  python3 -m venv .venv-preflight >/dev/null 2>&1 || {
    echo "venv failed; install python3-venv"; exit 1; }
fi
PY=.venv-preflight/bin/python
"$PY" -m pip -q install --upgrade pip >/dev/null 2>&1
"$PY" -m pip -q install playwright certifi >/dev/null 2>&1 || { echo "pip install failed"; exit 1; }
# Chromium needs its shared libraries; --with-deps needs root, so fall back quietly.
"$PY" -m playwright install --with-deps chromium >/dev/null 2>&1 \
  || "$PY" -m playwright install chromium >/dev/null 2>&1 \
  || { echo "playwright install failed"; exit 1; }
echo "dependency_install_seconds=$(( $(date +%s) - DEP_START ))" | tee "$OUT/cloud-install-time.txt"

echo
echo "=== M0.2 / M0.3 reachability and policy facts from this IP ==="
"$PY" preflight/check_reachability.py --out "$OUT/cloud-reachability.json" >/dev/null 2>&1 \
  && "$PY" - <<'EOF'
import json
d = json.load(open("preflight/results/cloud-reachability.json"))
print("egress:", d["egress_ip"].get("ipify"))
for t in d["targets"]:
    ips = t["resolved_ips"]
    ips = ips[:2] if isinstance(ips, list) else ips
    print(f"  {t['name']:24} HTTP {str(t['status']):5} {t['seconds']:>6}s "
          f"{t.get('bytes','-'):>9} ua_declared={t['user_agent_declared']} {ips}")
print("policy:", json.dumps(d["policy_facts"], indent=1))
EOF

echo
echo "=== A8.5 cold start: process start -> browser up -> first page loaded ==="
"$PY" - <<'EOF' 2>&1 | tee preflight/results/cloud-coldstart.txt
import asyncio, json, time
from playwright.async_api import async_playwright
async def main():
    t0 = time.time(); marks = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--disable-dev-shm-usage"])
        marks["browser_launch_s"] = round(time.time() - t0, 2)
        pg = await (await b.new_context()).new_page()
        await pg.goto("https://books.toscrape.com/", wait_until="load", timeout=60000)
        marks["first_page_loaded_s"] = round(time.time() - t0, 2)
        await b.close()
    print(json.dumps(marks))
asyncio.run(main())
EOF

echo
echo "=== M0.1 RAM: one browser process + 2 contexts + app under load ==="
"$PY" preflight/measure_ram.py --out "$OUT/cloud-ram.json" 2>&1 | tail -30

echo
echo "=== done in $(( $(date +%s) - START ))s ==="
echo "Paste back: $OUT/cloud-host.txt $OUT/cloud-reachability.json $OUT/cloud-ram.json $OUT/cloud-coldstart.txt"

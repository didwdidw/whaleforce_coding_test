#!/usr/bin/env bash
# M0.1 — RAM under load, measured on the host with system Python.
#
# The box has no container runtime and is not getting one: Zeabur installs k3s when it
# deploys, and a hand-installed copy risks colliding with it. Container-vs-host RSS differs
# by tens of MB, which does not change whether the app fits. Cold start is the figure that
# genuinely depends on the runtime, so it is measured after M1 deploys, in a pod.
#
#   bash ~/preflight/run_host_ram.sh
#
# Writes ~/cloud-ram.json. Installs a venv under ~/.venv-preflight and Chromium's shared
# libraries via apt; nothing else on the host is touched, and no provider API is called.
set -u

RESULT="$HOME/cloud-ram.json"
VENV="$HOME/.venv-preflight"

echo "=== host ==="
lsb_release -d 2>/dev/null || grep PRETTY /etc/os-release
echo "kernel=$(uname -srm)  nproc=$(nproc)"
free -m | head -3
echo

echo "=== baseline before we install or launch anything ==="
echo "--- top resident processes (this is what the 'baseline' actually consists of) ---"
ps -eo rss,comm --sort=-rss | head -12 | awk 'NR==1{print "  RSS_KB COMMAND"} NR>1{printf "  %7d %s\n",$1,$2}'
BASE_USED=$(free -m | awk '/^Mem:/{print $3}')
echo "--- system used: ${BASE_USED} MB ---"
echo

echo "=== dependencies ==="
if [ ! -x "$VENV/bin/python" ]; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv >/dev/null
  python3 -m venv "$VENV" || { echo "venv creation failed"; exit 1; }
fi
"$VENV/bin/python" -m pip -q install --upgrade pip >/dev/null 2>&1
"$VENV/bin/python" -m pip -q install playwright >/dev/null 2>&1 \
  || { echo "pip install playwright failed"; exit 1; }
# Browser shared libraries need root; the browser download itself does not.
sudo "$VENV/bin/python" -m playwright install-deps chromium >/dev/null 2>&1 \
  || echo "  note: install-deps returned non-zero; continuing (libraries may already be present)"
"$VENV/bin/python" -m playwright install chromium >/dev/null 2>&1 \
  || { echo "chromium download failed"; exit 1; }
echo "  playwright $("$VENV/bin/python" -m playwright --version 2>&1 | tail -1)"
echo "  python     $("$VENV/bin/python" -V)"
echo

echo "=== M0.1 measurement (two contexts, both loading, 20s hold) ==="
"$VENV/bin/python" "$HOME/preflight/measure_ram.py" --hold 20 --out "$RESULT" >/dev/null \
  || { echo "measurement failed"; exit 1; }

"$VENV/bin/python" - "$RESULT" <<'PY'
import json, sys

d = json.load(open(sys.argv[1]))
o = d["orchestration_baseline"]

print("baseline before launch")
print(f"  system used            : {o['system_used_mib_before_launch']} MiB")
print(f"  outside our tree, total: {o['outside_our_tree']['total_mib']} MiB")
print( "  largest                :", ", ".join(
    f"{x['comm']} {x['rss_mib']}" for x in o["outside_our_tree"]["top"][:6]))
print()
print("app footprint (our process tree only)")
for k, v in d["marks_mib"].items():
    print(f"  {k:28} {v:>8} MiB")
print(f"  {'PEAK':28} {d['app_tree_peak_rss_mib']:>8} MiB")
print( "  by process at peak      :", d["peak_by_process_mib"])
print()
print("swap")
for k, v in d["swap"].items():
    print(f"  {k:24} {v}")
print()
print("host meminfo :", d["platform_meminfo"])
print("load errors  :", d["load_errors"] or "none")
print("artifact DOM :", d["artifact_dom_chars"])
PY

echo
echo "=== done. Send back: $RESULT plus the output above ==="

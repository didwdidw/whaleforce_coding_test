"""M0.1 — resident memory of one browser process + 2 contexts + the app under load.

Launches a single Chromium process, opens two contexts (the S-11.8 concurrency model),
loads target pages in both at the same time, serialises the full DOM in each (what
artifact capture actually costs), and samples the resident set size of the whole process
tree throughout.

Run this inside the deployment container, not on a laptop: the number that matters is the
Linux one on the chosen tier. The local figure is only useful for picking a tier to test.
"""

import argparse
import asyncio
import json
import os
import subprocess
import time

from playwright.async_api import async_playwright

UA = "WhaleforceCodingTest-Task1/0.1 (contact: didwdidw0309@gmail.com)"
HEAVY = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
LIGHT = "https://books.toscrape.com/catalogue/category/books/nonfiction_13/index.html"


def total_rss_kb():
    """RSS of this process tree, in KiB. Works on both Linux and macOS."""
    out = subprocess.run(["ps", "-eo", "pid,ppid,rss,comm"], capture_output=True,
                         text=True, check=True).stdout
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
        except ValueError:
            continue
    tree, changed = {os.getpid()}, True
    while changed:
        changed = False
        for pid, ppid, _, _ in rows:
            if ppid in tree and pid not in tree:
                tree.add(pid)
                changed = True
    detail, total = {}, 0
    for pid, _, rss, comm in rows:
        if pid in tree:
            total += rss
            key = os.path.basename(comm)[:24]
            detail[key] = detail.get(key, 0) + rss
    return total, detail


def swap_used_kb():
    """Swap in use, in KiB. The host has ~2 GB of swap enabled, so it will not OOM at the
    peak — it will get slow, and a slow run inside the wall clock fails as `timeout`, two
    steps removed from its cause. A green peak on a swapping box is not a pass."""
    try:
        vals = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("SwapTotal", "SwapFree"):
                    vals[k] = int(v.split()[0])
        return vals["SwapTotal"] - vals["SwapFree"]
    except (OSError, KeyError, ValueError):
        return None


def system_used_kb():
    """System-wide used memory (MemTotal - MemAvailable), in KiB.

    On this host the orchestration layer (k3s + the Zeabur agent) occupies a baseline
    before our process starts. That baseline is reported separately from the app's own
    footprint so the two are never conflated.
    """
    try:
        vals = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("MemTotal", "MemAvailable"):
                    vals[k] = int(v.split()[0])
        return vals["MemTotal"] - vals["MemAvailable"]
    except (OSError, KeyError, ValueError):
        return None


def processes_outside_tree(top=12):
    """Largest resident processes that are not part of our own tree."""
    out = subprocess.run(["ps", "-eo", "pid,ppid,rss,comm"], capture_output=True,
                         text=True, check=True).stdout
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
        except ValueError:
            continue
    tree, changed = {os.getpid()}, True
    while changed:
        changed = False
        for pid, ppid, _, _ in rows:
            if ppid in tree and pid not in tree:
                tree.add(pid)
                changed = True
    outside = [(rss, os.path.basename(comm)) for pid, _, rss, comm in rows if pid not in tree]
    outside.sort(reverse=True)
    return {"total_mib": round(sum(r for r, _ in outside) / 1024, 1),
            "top": [{"comm": c, "rss_mib": round(r / 1024, 1)} for r, c in outside[:top]]}


def meminfo():
    """Container/host memory limits, where the platform exposes them."""
    info = {}
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path) as f:
                info["cgroup_limit_bytes"] = f.read().strip()
        except OSError:
            pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.split(":")[0] in ("MemTotal", "MemAvailable", "SwapTotal"):
                    info[line.split(":")[0]] = line.split(":", 1)[1].strip()
    except OSError:
        info["platform"] = "no /proc/meminfo (not Linux)"
    return info


def swap_verdict(samples, before_kb):
    """Did the measurement push the box into swap? A peak reached via swap is not a pass."""
    seen = [s["swap_used_kb"] for s in samples if s.get("swap_used_kb") is not None]
    if not seen:
        return {"observable": False, "note": "no /proc/meminfo (not Linux)"}
    peak = max(seen)
    baseline = before_kb if before_kb is not None else min(seen)
    grew = peak - baseline
    return {
        "observable": True,
        "baseline_mib": round(baseline / 1024, 1),
        "peak_mib": round(peak / 1024, 1),
        "growth_during_run_mib": round(grew / 1024, 1),
        # A little pre-existing swap is normal; growth during our run is the signal.
        "touched_by_this_run": grew > 4096,
        "verdict": "PASS - no swap growth" if grew <= 4096 else
                   "FAIL - the peak was reached by swapping, not by fitting in RAM",
    }


async def sample_loop(samples, stop):
    while not stop.is_set():
        rss, detail = total_rss_kb()
        samples.append({"t": round(time.time(), 2), "rss_kb": rss, "by_proc": detail,
                        "swap_used_kb": swap_used_kb(), "system_used_kb": system_used_kb()})
        await asyncio.sleep(0.4)


async def run(hold):
    samples, marks, errs = [], {}, []
    stop = asyncio.Event()
    sampler = asyncio.create_task(sample_loop(samples, stop))
    marks["baseline_kb"] = total_rss_kb()[0]
    # Captured before anything of ours is launched.
    orchestration_baseline = {"system_used_kb_before_launch": system_used_kb(),
                              "swap_used_kb_before_launch": swap_used_kb(),
                              "outside_our_tree": processes_outside_tree()}

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-dev-shm-usage"])
        await asyncio.sleep(1.5)
        marks["browser_launched_kb"] = total_rss_kb()[0]

        c1 = await browser.new_context(user_agent=UA)
        c2 = await browser.new_context(user_agent=UA)
        p1, p2 = await c1.new_page(), await c2.new_page()
        await asyncio.sleep(1.0)
        marks["two_contexts_idle_kb"] = total_rss_kb()[0]

        async def load(page, url):
            try:
                await page.goto(url, wait_until="load", timeout=60_000)
            except Exception as e:  # noqa: BLE001 - recorded, not swallowed
                errs.append(f"{url}: {type(e).__name__}: {e}")

        t0 = time.time()
        await asyncio.gather(load(p1, HEAVY), load(p2, LIGHT))
        marks["concurrent_load_seconds"] = round(time.time() - t0, 2)
        marks["both_loaded_kb"] = total_rss_kb()[0]

        # Artifact capture: full DOM serialisation in both contexts at once.
        sizes = dict(zip(
            ("heavy", "light"),
            await asyncio.gather(
                p1.evaluate("() => document.documentElement.outerHTML.length"),
                p2.evaluate("() => document.documentElement.outerHTML.length"),
            ),
        ))
        marks["after_artifact_capture_kb"] = total_rss_kb()[0]

        # Screenshots are the other memory spike in an evidence bundle.
        shots = await asyncio.gather(p1.screenshot(full_page=False), p2.screenshot(full_page=False))
        marks["after_screenshots_kb"] = total_rss_kb()[0]
        marks["screenshot_bytes"] = [len(s) for s in shots]

        await asyncio.sleep(hold)
        await browser.close()

    stop.set()
    await sampler
    peak = max(samples, key=lambda s: s["rss_kb"])
    sys_used = system_used_kb()
    return {
        "platform_meminfo": meminfo(),
        "orchestration_baseline": {
            **orchestration_baseline,
            "system_used_mib_before_launch": (
                round(orchestration_baseline["system_used_kb_before_launch"] / 1024, 1)
                if orchestration_baseline["system_used_kb_before_launch"] else None),
            "system_used_mib_after_teardown": round(sys_used / 1024, 1) if sys_used else None,
        },
        "marks_kb": marks,
        "marks_mib": {k: round(v / 1024, 1) for k, v in marks.items()
                      if k.endswith("_kb")},
        "app_tree_peak_rss_mib": round(peak["rss_kb"] / 1024, 1),
        "swap": swap_verdict(samples, orchestration_baseline["swap_used_kb_before_launch"]),
        "peak_by_process_mib": {k: round(v / 1024, 1) for k, v in peak["by_proc"].items()},
        "artifact_dom_chars": sizes,
        "load_errors": errs,
        "samples": len(samples),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=5.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    result = asyncio.run(run(a.hold))
    text = json.dumps(result, indent=1)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()

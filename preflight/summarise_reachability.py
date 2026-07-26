"""Print a short verdict from a check_reachability.py result file.

Reads the JSON so the decision is made from recorded evidence rather than from scrollback.
Exit status is the verdict: 0 all clear, 2 a target is blocked, 3 the TLS control failed
(a box problem, not a site problem), 4 the file could not be read.
"""

import json
import sys

# Which targets each promised record depends on. A block here is not recoverable by us.
CRITICAL = {
    "wikipedia_article": "OP-4, OP-5",
    "wikipedia_robots": "robots enforcement (S-2.3)",
    "books_home": "OP-6",
    "books_category": "OP-6",
}
SEAM_ONLY = {"sec_robots", "sec_archives_index", "sec_submissions_api"}
EXPECTED_NON_200 = {"books_robots": 404, "sec_robots_no_ua": 403}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "cloud-reachability.json"
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cannot read {path}: {e}")
        return 4

    h = d.get("host", {})
    print(f"host      : python {h.get('python')} | {h.get('platform')}")
    print(f"openssl   : {h.get('openssl')}")
    print(f"egress ip : {d['egress_ip'].get('ipify')}")
    print(f"measured  : {d['measured_at']}")
    print()

    by_name = {t["name"]: t for t in d["targets"]}
    control = by_name.get("control_example_com", {})
    control_ok = control.get("status") == 200

    print(f"{'target':24} {'HTTP':>5} {'secs':>7} {'bytes':>10}  verdict")
    blocked, unexpected = [], []
    for t in d["targets"]:
        name, status = t["name"], t["status"]
        expected = EXPECTED_NON_200.get(name, 200)
        ok = status == expected
        if ok:
            verdict = "ok" if expected == 200 else f"ok (expected {expected})"
        elif status in (401, 403, 429, 451):
            verdict = f"** BLOCKED ({status}) **"
            blocked.append(name)
        elif status is None:
            verdict = f"** NO RESPONSE: {t.get('error', '')[:60]} **"
            unexpected.append(name)
        else:
            verdict = f"** UNEXPECTED (wanted {expected}) **"
            unexpected.append(name)
        print(f"{name:24} {str(status):>5} {t['seconds']:>7} "
              f"{str(t.get('bytes', '-')):>10}  {verdict}")

    print()
    print("policy facts:", json.dumps(d.get("policy_facts", {}), ensure_ascii=False))
    print()

    if not control_ok:
        print("VERDICT: TLS CONTROL FAILED — https://example.com/ did not return 200.")
        print("  This is a problem with the box, not with the target sites. Nothing above")
        print("  can be read as a site-level block until the control passes.")
        print("  Most likely a missing CA bundle: sudo apt-get update && "
              "sudo apt-get install -y ca-certificates")
        return 3

    hard = [n for n in blocked + unexpected if n in CRITICAL]
    seam = [n for n in blocked + unexpected if n in SEAM_ONLY]

    if hard:
        print("VERDICT: STOP AND REPORT. Targets a promised record depends on are blocked:")
        for n in hard:
            print(f"  - {n}  ({CRITICAL.get(n, 'critical')})")
        print("  Do not substitute a site (S-3.5, spec §13 M0). This needs a different host.")
        return 2
    if seam:
        print("VERDICT: STOP AND REPORT. SEC is blocked; Wikipedia and books.toscrape are fine.")
        print(f"  Affected: {', '.join(seam)}")
        print("  This is Task 2 seam scope only — OP-4..OP-7 are unaffected.")
        return 2
    print("VERDICT: ALL CLEAR. Every target reachable from this IP; "
          "expected non-200s behaved as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# M0.2 Runbook — reachability from the production host

**Target:** Tencent Cloud / Ashburn US, `43.166.128.37`, rented through Zeabur (A9.10).
**Scope of this run: M0.2 only.** RAM, cold start and everything else come after, and only if this
passes. Nothing here installs a package, makes a provider API call, or touches `api_keys/`.

**Stop conditions — report, do not work around (spec §13 M0, S-3.5):**

| Outcome | Meaning | Action |
|---|---|---|
| TLS control fails | The box has no usable CA bundle. Not a site block. | Install `ca-certificates`, re-run. |
| Wikipedia or books.toscrape blocked | OP-4…OP-7 all depend on these. | **Stop.** Report; you change provider. |
| SEC blocked, others fine | Task 2 seam scope only. | **Stop.** Report; leave it to the seam. |
| All clear | Proceed to M0.1 / cold start. | — |

The summariser encodes these as exit codes: `0` all clear, `2` blocked, `3` TLS control failed.

---

## Step 1 — copy `preflight/` to the box (from your Mac)

Only `preflight/` moves. `api_keys/` is never part of the transfer.

```bash
cd /Users/tim/Desktop/whaleforce_coding_test
rsync -av --exclude='results/' --exclude='dist/' --exclude='__pycache__/' \
  preflight/ SSH_USER@43.166.128.37:~/preflight/
```

Replace `SSH_USER` with whatever Zeabur gives you. If it needs a non-standard port or an identity
file, add `-e 'ssh -p PORT -i /path/to/key'`.

### If the Zeabur console is a web terminal and `rsync` is not available

Paste this on the box instead — it reconstructs the two files from a base64 bundle, no transfer and
no network fetch. Get the blob with `cat preflight/dist/reachability-bundle.b64` on your Mac (one
long line) and substitute it for `PASTE_BLOB_HERE`:

```bash
mkdir -p ~/preflight && cd ~/preflight && cat > bundle.b64 <<'EOF'
PASTE_BLOB_HERE
EOF
base64 -d < bundle.b64 | tar xzf - && ls -l *.py
```

## Step 2 — confirm the environment (do not assume 24.04 / Python 3.12)

```bash
lsb_release -a 2>/dev/null || cat /etc/os-release
python3 -V
python3 -c "import ssl, json, urllib.request; print('stdlib ok |', ssl.OPENSSL_VERSION)"
nproc; free -m; df -h /
```

The reachability check is **standard library only** and runs on Python 3.7+, so 22.04's Python 3.10
is fine and no `venv` or `pip` is needed. If `python3 -c` fails on `ssl`, the base image lacks the
TLS module — report that rather than working around it.

Note for later, not now: this box is also the M0.1 RAM target, and the RAM script does need
Playwright. Per your note, deployment will use a custom Dockerfile from the Playwright base image
rather than Zeabur's Python auto-detection, so the RAM measurement should be taken inside that image
to be representative. That is the next step, not this one.

## Step 3 — run the check

```bash
cd ~ && python3 preflight/check_reachability.py --out ~/cloud-reachability.json > /dev/null
python3 preflight/summarise_reachability.py ~/cloud-reachability.json; echo "exit=$?"
```

Total traffic is ten requests: one TLS control, two Wikipedia, three books.toscrape, four SEC
(one of them deliberately without the declared User-Agent). Well inside every pacing rule.

## Step 4 — read the control line first

`control_example_com` must be `200`. If it is not, everything below it is meaningless — a missing CA
bundle makes every HTTPS target look blocked:

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates
# then re-run Step 3
```

## Step 5 — send back

```bash
cat ~/cloud-reachability.json
```

Paste that plus the Step 2 output and the Step 3 summary table. The JSON holds no secrets: egress IP,
status codes, timings, byte counts, content hashes and the robots assertions.

---

## What each row means

| Target | Expected | Depends on it |
|---|---|---|
| `control_example_com` | 200 | Nothing — it validates the box's TLS |
| `wikipedia_article` (S&P 500) | 200 | **OP-4, OP-5** |
| `wikipedia_robots` | 200 | robots enforcement, S-2.3 / DEV-13 |
| `books_home` | 200 | **OP-6** (DEV-06 entry point) |
| `books_robots` | **404** — the site has no robots.txt | Confirms §3.4 |
| `books_category` (Nonfiction) | 200 | **OP-6, OP-7** |
| `sec_robots` | 200 | Task 2 seam |
| `sec_archives_index` (CIK 320193) | 200 | Task 2 seam — the `Allow`ed path |
| `sec_submissions_api` (data.sec.gov) | 200 | Task 2 seam lookup |
| `sec_robots_no_ua` | **403** — SEC rejects an undeclared UA | Confirms A9.8 |

Both non-200s are expected results, not failures. A `200` on `sec_robots_no_ua` would itself be a
finding: it would mean A9.8's premise no longer holds.

## Residential control run, for comparison

Taken from `1.171.14.75` (TW residential) on 2026-07-26 — every target as expected, so any difference
on the Tencent IP is attributable to the network, not to the harness. Full record in
`preflight/results/reachability-local-residential.json`.

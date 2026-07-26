"""M0.2 / M0.3 — reachability and policy facts as seen from the deployment IP.

Datacenter IPs are treated differently from residential ones, so this must run from the
box that will actually serve the system. Records the egress IP, the resolved address and
status code for every target, and re-fetches the policy documents §3.4 depends on.

Also checks SEC both with and without the declared User-Agent, so S-2.16 is a measured
requirement rather than an assumed one.
"""

import argparse
import gzip
import hashlib
import io
import json
import socket
import ssl
import time
import zlib
import urllib.error
import urllib.parse
import urllib.request

UA = "WhaleforceCodingTest-Task1/0.1 (contact: didwdidw0309@gmail.com)"


def ssl_context():
    """Prefer certifi's bundle: some Python builds ship without usable system CA paths."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def decode_body(raw, encoding):
    """SEC requires Accept-Encoding: gzip, deflate (S-2.16), so responses arrive compressed."""
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw

TARGETS = [
    ("wikipedia_article", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", UA),
    ("wikipedia_robots", "https://en.wikipedia.org/robots.txt", UA),
    ("books_home", "https://books.toscrape.com/", UA),
    ("books_robots", "https://books.toscrape.com/robots.txt", UA),
    ("books_category", "https://books.toscrape.com/catalogue/category/books/nonfiction_13/index.html", UA),
    ("sec_robots", "https://www.sec.gov/robots.txt", UA),
    ("sec_archives_index", "https://www.sec.gov/Archives/edgar/data/320193/", UA),
    ("sec_submissions_api", "https://data.sec.gov/submissions/CIK0000320193.json", UA),
    # Same path without a declared contact UA: S-2.16 says SEC requires one.
    ("sec_robots_no_ua", "https://www.sec.gov/robots.txt", "python-urllib/3"),
]


def fetch(url, ua, timeout=30):
    host = urllib.parse.urlsplit(url).hostname
    rec = {"url": url, "user_agent_declared": ua != "python-urllib/3"}
    try:
        rec["resolved_ips"] = sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443)})
    except OSError as e:
        rec["resolved_ips"] = f"DNS FAILED: {e}"

    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "*/*",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
            wire = r.read()
            body = decode_body(wire, r.headers.get("Content-Encoding"))
            rec.update({
                "status": r.status,
                "final_url": r.geturl(),
                "seconds": round(time.time() - t0, 3),
                "wire_bytes": len(wire),
                "bytes": len(body),
                "content_type": r.headers.get("Content-Type"),
                "content_encoding": r.headers.get("Content-Encoding"),
                "sha256": hashlib.sha256(body).hexdigest(),
            })
    except urllib.error.HTTPError as e:
        rec.update({"status": e.code, "seconds": round(time.time() - t0, 3),
                    "error": f"HTTPError {e.code} {e.reason}",
                    "body_head": e.read()[:300].decode("utf-8", "replace")})
    except Exception as e:  # noqa: BLE001 - a failure here is the finding
        rec.update({"status": None, "seconds": round(time.time() - t0, 3),
                    "error": f"{type(e).__name__}: {e}"})
    return rec


def egress_ip():
    """The address the target sites actually see."""
    out = {}
    for name, url in (("ipify", "https://api.ipify.org?format=json"),
                      ("cloudflare", "https://cloudflare.com/cdn-cgi/trace")):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as r:
                out[name] = r.read()[:400].decode("utf-8", "replace").strip()
        except Exception as e:  # noqa: BLE001
            out[name] = f"{type(e).__name__}: {e}"
    return out


POLICY_CHECKS = {
    "wikipedia_robots": [
        ("star_block_disallows_/w/", "Disallow: /w/"),
        ("star_block_disallows_Special", "Disallow: /wiki/Special:"),
        ("star_block_disallows_/api/", "Disallow: /api/"),
    ],
    "sec_robots": [
        ("allows_Archives_edgar_data", "Allow: /Archives/edgar/data"),
        ("disallows_cgi_bin", "Disallow: /cgi-bin"),
        ("disallows_search", "Disallow: /search/"),
    ],
}


def policy_facts():
    """Re-verify the §3.4 strings from the deployment IP, not from a local cache."""
    facts = {}
    for key, url in (("wikipedia_robots", "https://en.wikipedia.org/robots.txt"),
                     ("sec_robots", "https://www.sec.gov/robots.txt")):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
                text = decode_body(r.read(), r.headers.get("Content-Encoding")).decode(
                    "utf-8", "replace")
            facts[key] = {c: (needle in text) for c, needle in POLICY_CHECKS[key]}
            facts[key]["bytes"] = len(text)
            if key == "wikipedia_robots":
                # A Crawl-delay that belongs to a named bot does not apply to us.
                star = text.split("User-agent: *", 1)[-1].split("User-agent:", 1)[0]
                facts[key]["crawl_delay_in_star_block"] = "Crawl-delay" in star
        except Exception as e:  # noqa: BLE001
            facts[key] = {"error": f"{type(e).__name__}: {e}"}
    # books.toscrape is expected to have no robots.txt at all (404).
    facts["books_robots_status"] = fetch("https://books.toscrape.com/robots.txt", UA)["status"]
    return facts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    result = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "egress_ip": egress_ip(),
        "targets": [dict(name=n, **fetch(u, ua)) for n, u, ua in TARGETS],
        "policy_facts": policy_facts(),
    }
    text = json.dumps(result, indent=1)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()

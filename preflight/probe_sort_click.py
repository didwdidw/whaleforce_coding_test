"""M0.6 — how to actually trigger a sort on the S&P 500 constituents table.

The "CIK" and "Date added" header cells contain wikilinks, so clicking the header's
centre navigates away instead of sorting. This measures the header geometry, finds a
click point inside the `th` that misses every `<a>`, performs the sort, and records the
order the page produced (not the order we would compute).
"""

import json

from playwright.sync_api import sync_playwright

UA = "WhaleforceCodingTest-Task1/0.1 (contact: didwdidw0309@gmail.com)"
SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

HEADER_GEOM = """() => {
  const t = document.querySelector('table#constituents');
  return [...t.querySelectorAll('th.headerSort')].map(th => {
    const r = th.getBoundingClientRect();
    return {
      text: th.innerText.trim(), ariaSort: th.getAttribute('aria-sort'),
      w: Math.round(r.width), h: Math.round(r.height),
      links: [...th.querySelectorAll('a')].map(a => {
        const ar = a.getBoundingClientRect();
        return {href: a.getAttribute('href'),
                left: Math.round(ar.left - r.left), right: Math.round(ar.right - r.left)};
      }),
    };
  });
}"""

TOP_ROWS = """() => {
  const t = document.querySelector('table#constituents');
  const hs = [...t.querySelectorAll('th.headerSort')].map(th =>
    ({text: th.innerText.trim(), ariaSort: th.getAttribute('aria-sort'), cls: th.className}));
  return {headers: hs, top: [...t.querySelectorAll('tbody tr')].slice(1, 6).map(r =>
    [...r.querySelectorAll('th,td')].map(c => c.innerText.trim()))};
}"""


def main():
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(user_agent=UA).new_page()
        page.goto(SP500, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_selector("table#constituents th.headerSort", timeout=30_000)
        out["header_geometry"] = page.evaluate(HEADER_GEOM)

        # Click the sort-arrow zone at the right edge of the CIK header, past every link.
        cik = page.locator("table#constituents th.headerSort").filter(has_text="CIK").first
        box = cik.bounding_box()
        out["cik_box"] = box
        cik.click(position={"x": box["width"] - 6, "y": box["height"] / 2})
        page.wait_for_timeout(600)
        out["url_after_click"] = page.url
        out["after_1_click"] = page.evaluate(TOP_ROWS)

        cik.click(position={"x": box["width"] - 6, "y": box["height"] / 2})
        page.wait_for_timeout(600)
        out["after_2_clicks"] = page.evaluate(TOP_ROWS)
        browser.close()
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

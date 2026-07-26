"""M0.6 — OP-4 operational probe.

Answers three questions the eval cases depend on:
  1. When does jquery.tablesorter finish wiring the headers (can we click a sort header
     at domcontentloaded, or must we wait for it)?
  2. Are the wikitable `id` attributes stable across loads (can an anchor pin one)?
  3. Do header texts collide between the two sortable tables on the S&P 500 article?
Also performs one real sort click and reports the resulting top row, so the
numeric-vs-lexicographic question is answered by the page rather than assumed.
"""

import json

from playwright.sync_api import sync_playwright

UA = "WhaleforceCodingTest-Task1/0.1 (contact: didwdidw0309@gmail.com)"
SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
GDP = "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)"


def table_shape(page):
    return page.evaluate("""() => [...document.querySelectorAll('table.wikitable')].map((t,i) => ({
      i, id: t.id || null, sortable: t.classList.contains('sortable'),
      headerSortCount: t.querySelectorAll('th.headerSort').length,
      allHeaderTexts: [...t.querySelectorAll('thead th, tr:first-child th, tr:nth-child(2) th')]
        .map(th => th.innerText.trim().replace(/\\s+/g,' ')),
    }))""")


def main():
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()

        page.goto(SP500, wait_until="domcontentloaded", timeout=45_000)
        out["sp500_at_domcontentloaded"] = table_shape(page)
        page.wait_for_selector("table#constituents th.headerSort", timeout=30_000)
        out["sp500_after_headerSort_wait"] = table_shape(page)

        # Sort #constituents by CIK ascending and report what the page produced.
        cik = page.locator("table#constituents th.headerSort").filter(has_text="CIK")
        out["cik_header_matches"] = cik.count()
        out["url_before_click"] = page.url
        cik.first.click()
        page.wait_for_timeout(600)
        out["url_after_click"] = page.url
        out["constituents_still_present"] = page.evaluate(
            "() => !!document.querySelector('table#constituents')"
        )
        out["sp500_cik_asc_top5"] = page.evaluate(
            """() => {
              const t = document.querySelector('table#constituents');
              if (!t) return 'table#constituents gone';
              const th = [...t.querySelectorAll('th')].find(h => h.innerText.trim().startsWith('CIK'));
              return {
                headerClass: th && th.className, ariaSort: th && th.getAttribute('aria-sort'),
                rows: [...t.querySelectorAll('tbody tr')].slice(0, 6).map(r =>
                  [...r.querySelectorAll('th,td')].map(c => c.innerText.trim())),
              };
            }"""
        )

        # Second load: are ids stable?
        page.goto(GDP, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_selector("table.wikitable.sortable th.headerSort", timeout=30_000)
        out["gdp_load1"] = table_shape(page)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("table.wikitable.sortable th.headerSort", timeout=30_000)
        out["gdp_load2"] = table_shape(page)
        browser.close()
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""M0.6 — inspect and pin the target pages for OP-4..OP-7.

Reports the structural facts each eval case depends on: how many sortable tables a
Wikipedia article has and their headers (the "second table" trap), which elements are
collapsed and whether their expand control is stable, and the counter/pager strings
books.toscrape exposes. Read-only; one page load per target.
"""

import json
import sys

from playwright.sync_api import sync_playwright

UA = "WhaleforceCodingTest-Task1/0.1 (contact: didwdidw0309@gmail.com)"

TARGETS = {
    "WIKI_SP500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "WIKI_GDP": "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)",
    "WIKI_APPLE": "https://en.wikipedia.org/wiki/Apple_Inc.",
    "BT_HOME": "https://books.toscrape.com/",
    "BT_NONFIC": "https://books.toscrape.com/catalogue/category/books/nonfiction_13/index.html",
    "BT_FICTION": "https://books.toscrape.com/catalogue/category/books/fiction_10/index.html",
    "BT_POETRY": "https://books.toscrape.com/catalogue/category/books/poetry_23/index.html",
    "BT_ATTIC": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
}

WIKI_PROBE = """() => {
  const out = {tables: [], collapsibles: [], title: document.title};
  document.querySelectorAll('table.wikitable').forEach((t, i) => {
    const sortable = t.classList.contains('sortable');
    const headers = [...t.querySelectorAll('tr:first-child th')]
      .map(th => th.innerText.trim().replace(/\\s+/g, ' '));
    const sortableHeaders = [...t.querySelectorAll('th.headerSort, th[tabindex]')]
      .map(th => th.innerText.trim().replace(/\\s+/g, ' '));
    out.tables.push({
      index: i, sortable, id: t.id || null,
      caption: (t.querySelector('caption')?.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 120),
      classes: t.className,
      rows: t.querySelectorAll('tr').length,
      headers, sortableHeaders,
      firstDataRow: [...(t.querySelectorAll('tbody tr')[1]?.querySelectorAll('th,td') || [])]
        .map(c => c.innerText.trim().replace(/\\s+/g, ' ').slice(0, 40)),
    });
  });
  document.querySelectorAll('.mw-collapsed, .mw-collapsible').forEach((e, i) => {
    const toggle = e.querySelector('.mw-collapsible-toggle, .mw-collapsible-text, [role="button"]');
    out.collapsibles.push({
      index: i,
      collapsedNow: e.classList.contains('mw-collapsed'),
      tag: e.tagName, id: e.id || null, classes: e.className.slice(0, 160),
      role: e.getAttribute('role'), ariaExpanded: e.getAttribute('aria-expanded'),
      title: (e.querySelector('.navbox-title, .navbar, th, caption, .mw-collapsible-toggle')?.innerText || '')
        .trim().replace(/\\s+/g, ' ').slice(0, 100),
      toggleText: (toggle?.innerText || '').trim().slice(0, 40),
      toggleAria: toggle?.getAttribute('aria-expanded'),
    });
  });
  return out;
}"""

BT_PROBE = """() => ({
  title: document.title.trim().replace(/\\s+/g, ' '),
  h1: (document.querySelector('h1')?.innerText || '').trim(),
  counter: (document.querySelector('form.form-horizontal strong, .form-horizontal')?.innerText || '')
    .trim().replace(/\\s+/g, ' ').slice(0, 160),
  pager: (document.querySelector('ul.pager')?.innerText || '').trim().replace(/\\s+/g, ' '),
  hasNext: !!document.querySelector('li.next a'),
  nextHref: document.querySelector('li.next a')?.getAttribute('href') || null,
  items: document.querySelectorAll('article.product_pod').length,
  firstItemTitle: document.querySelector('article.product_pod h3 a')?.getAttribute('title') || null,
  sidebarCategories: [...document.querySelectorAll('.side_categories ul ul li a')]
    .map(a => a.innerText.trim()).slice(0, 60),
  productInfo: [...document.querySelectorAll('table.table-striped tr')]
    .map(tr => [tr.querySelector('th')?.innerText.trim(), tr.querySelector('td')?.innerText.trim()]),
  prices: [...document.querySelectorAll('article.product_pod .price_color')].map(e => e.innerText.trim()),
})"""


def main() -> None:
    wanted = sys.argv[1:] or list(TARGETS)
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        for alias in wanted:
            url = TARGETS[alias]
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            probe = WIKI_PROBE if alias.startswith("WIKI") else BT_PROBE
            results[alias] = {
                "url": url,
                "status": resp.status if resp else None,
                "final_url": page.url,
                "probe": page.evaluate(probe),
            }
        browser.close()
    print(json.dumps(results, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

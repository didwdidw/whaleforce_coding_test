"""M0.6 — OP-5 target stability probe on the Apple Inc. article.

Collapsed state on Wikipedia is partly authored (`mw-collapsed` in the wikitext) and
partly computed by the `jquery.makeCollapsible` module (`autocollapse`). "The first
collapsed box" therefore means different elements before and after that module runs.
This records the collapsed set at three points, checks it is stable across two loads,
and performs one real expand to confirm what the state transition looks like in the DOM.
"""

import json

from playwright.sync_api import sync_playwright

UA = "WhaleforceCodingTest-Task1/0.1 (contact: didwdidw0309@gmail.com)"
APPLE = "https://en.wikipedia.org/wiki/Apple_Inc."

COLLAPSED_SET = """() => {
  const all = [...document.querySelectorAll('.mw-collapsible')];
  const collapsed = all.filter(e => e.classList.contains('mw-collapsed'));
  return {
    total: all.length,
    collapsedCount: collapsed.length,
    togglesPresent: document.querySelectorAll('.mw-collapsible-toggle').length,
    collapsed: collapsed.map(e => {
      const t = e.querySelector('.mw-collapsible-toggle');
      const titleCell = e.querySelector('.navbox-title, caption, th');
      const firstGroup = e.querySelector('tr:has(.navbox-group) .navbox-group, .navbox-group');
      return {
        title: (titleCell?.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 90),
        classes: e.className.slice(0, 120),
        toggleText: (t?.innerText || '').trim(),
        toggleAriaExpanded: t?.getAttribute('aria-expanded'),
        toggleTag: t?.tagName,
        firstGroupLabel: (firstGroup?.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 90),
        contentInDomWhileCollapsed: e.innerText.length,
      };
    }),
  };
}"""


def main():
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(user_agent=UA).new_page()

        page.goto(APPLE, wait_until="domcontentloaded", timeout=45_000)
        out["at_domcontentloaded"] = page.evaluate(COLLAPSED_SET)
        page.wait_for_selector(".mw-collapsible-toggle", timeout=30_000)
        page.wait_for_timeout(1_000)
        out["after_makeCollapsible"] = page.evaluate(COLLAPSED_SET)

        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(".mw-collapsible-toggle", timeout=30_000)
        page.wait_for_timeout(1_000)
        out["after_reload"] = page.evaluate(COLLAPSED_SET)

        # Expand the first collapsed box and record the transition.
        first = page.locator(".mw-collapsible.mw-collapsed").first
        toggle = first.locator(".mw-collapsible-toggle").first
        out["expand"] = {"toggle_text_before": toggle.inner_text().strip()}
        toggle.click()
        page.wait_for_timeout(800)
        out["expand"]["url_after"] = page.url
        out["expand"]["result"] = page.evaluate(
            """() => {
              const e = document.querySelectorAll('.mw-collapsible')[0];
              const boxes = [...document.querySelectorAll('.mw-collapsible')];
              const target = boxes.find(b => b.querySelector('.mw-collapsible-toggle')
                && !b.classList.contains('mw-collapsed')
                && b.querySelector('.mw-collapsible-toggle').innerText.trim().match(/hide/i));
              return {
                stillCollapsedCount: document.querySelectorAll('.mw-collapsed').length,
                sampleToggleTexts: [...document.querySelectorAll('.mw-collapsible-toggle')]
                  .slice(0, 6).map(t => t.innerText.trim() + '|' + t.getAttribute('aria-expanded')),
              };
            }"""
        )
        browser.close()
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

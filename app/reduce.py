"""Snapshot reduction, rule version `reduce/v1.0`.

The bounded view of a page a model call is allowed to see: interactive elements, the region
around candidate anchors, and nothing else. Raw snapshots are never sent to a model (A7.2),
and verification never runs against this output — it runs against the full stored artifact
(A7.4), because verifying against the trimmed view would make verification circular.

Reduction is goal-scoped rather than document-order-scoped. The first version filled its
whole element budget with Wikipedia's navigation chrome and dropped the sort headers the
task needed, so candidate anchor regions are resolved first and interactive elements are
ranked by distance from those regions.

What was dropped is counted by category and recorded per call (A7.3). Without that, a wrong
answer cannot be attributed between *the model reasoned badly* and *we trimmed away the
evidence*, which is most of the reason for having a trace at all.

Carried over from the M0 measurement version (`reduce/v0.2-preflight`) with a production
version identifier, so the token and cost figures measured at M0 still describe what is
sent. v1.1 adds the current value of form fields: without it the view cannot distinguish a
filled field from an empty one, and the model comparison recorded a "wrong action" that was
really a blind spot in what we showed it.
"""

from __future__ import annotations

from typing import Any

RULE_VERSION = "reduce/v1.1"

REDUCE_JS = r"""
(args) => {
  const {terms, maxInteractive, maxAnchorRegions, maxRowsPerRegion} = args;
  const dropped = {};
  const bump = (k, n) => { dropped[k] = (dropped[k] || 0) + (n === undefined ? 1 : n); };

  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  // Visible text outranks `title`. Wikipedia's sort headers all carry
  // title="Sort ascending", so a title-first order makes every column look identical.
  const accName = el => norm(
    el.getAttribute('aria-label') ||
    el.innerText ||
    (el.labels && el.labels[0] && el.labels[0].innerText) ||
    el.value || el.getAttribute('alt') || el.getAttribute('title') || ''
  ).slice(0, 90);

  let refN = 0;
  const refFor = el => { const r = 'e' + (++refN); el.setAttribute('data-agent-ref', r); return r; };

  // --- 1. Candidate anchor regions -----------------------------------------------------
  // The smallest table / list / definition-list / section containing a goal term, rendered
  // as bounded rows. Resolved first so interactive elements can be ranked against them.
  const lowerTerms = terms.map(t => t.toLowerCase()).filter(t => t.length > 2);
  const containerOf = el => el.closest(
    'table, dl, ul.pager, form, section, div.product_main, div.sub-header, ' +
    'div.mw-collapsible, div.side_categories') || el.parentElement;

  const seen = new Set();
  const regions = [];
  const anchorContainers = [];
  const CANDIDATE_TEXT = 'th, td, dt, dd, h1, h2, h3, h4, label, strong, caption, li.current, li.next';

  for (const el of document.querySelectorAll(CANDIDATE_TEXT)) {
    if (!visible(el)) continue;
    const raw = norm(el.innerText);
    const t = raw.toLowerCase();
    if (!t || !lowerTerms.some(term => t.includes(term))) continue;
    const c = containerOf(el);
    if (!c || seen.has(c)) continue;
    seen.add(c);
    if (regions.length >= maxAnchorRegions) { bump('anchor_region_over_cap'); continue; }

    const region = {ref: refFor(c), tag: c.tagName.toLowerCase(),
                    id: c.id || null, matched_on: raw.slice(0, 60)};
    if (c.tagName === 'TABLE') {
      const caption = norm(c.querySelector('caption')?.innerText);
      if (caption) region.caption = caption.slice(0, 120);
      const rows = [...c.rows];
      region.total_rows = rows.length;
      region.rows = rows.slice(0, maxRowsPerRegion).map(r =>
        [...r.cells].map(cell => norm(cell.innerText).slice(0, 60)));
      if (rows.length > maxRowsPerRegion) bump('table_rows', rows.length - maxRowsPerRegion);
    } else if (c.tagName === 'DL') {
      region.pairs = [...c.children].map(x => norm(x.innerText).slice(0, 80))
        .slice(0, maxRowsPerRegion);
    } else {
      region.text = norm(c.innerText).slice(0, 600);
    }
    regions.push(region);
    anchorContainers.push(c);
  }

  // --- 2. Interactive elements, ranked -------------------------------------------------
  const INTERACTIVE = 'a[href], button, input, select, textarea, summary, [role="button"],' +
    '[role="link"], [role="tab"], [role="checkbox"], [onclick], [tabindex]:not([tabindex="-1"]),' +
    'th.headerSort, .mw-collapsible-toggle, li.next a, li.previous a';
  // Site chrome is never the target of a task, and in document order it would otherwise
  // consume the entire element budget before the content is reached.
  const CHROME = 'nav, header, footer, [role="navigation"], [role="banner"],' +
    '[role="contentinfo"], #mw-panel, #mw-navigation, #vector-toc, #p-lang-btn,' +
    '.mw-footer, .vector-header, .vector-sticky-header, .mw-jump-link,' +
    '.mw-editsection, .navbar, .sitenav';
  const MAIN = '#mw-content-text, main, [role="main"], article, #content_inner,' +
    '.product_main, .page_inner';

  const rank = el => {
    if (anchorContainers.some(c => c.contains(el))) return 0;
    if (el.closest(CHROME)) return 3;
    if (el.closest(MAIN)) return 1;
    return 2;
  };

  const cands = [];
  for (const el of document.querySelectorAll(INTERACTIVE)) {
    if (!visible(el)) { bump('interactive_invisible'); continue; }
    const name = accName(el);
    // A bare link with no accessible name carries nothing a planner can act on.
    if (!name && el.tagName === 'A') { bump('interactive_unnamed_link'); continue; }
    cands.push({el, name, r: rank(el)});
  }
  cands.sort((a, b) => a.r - b.r);

  const interactive = [];
  for (const {el, name, r} of cands) {
    if (interactive.length >= maxInteractive) {
      bump(r === 3 ? 'interactive_chrome_over_cap' : 'interactive_over_cap');
      continue;
    }
    const role = el.getAttribute('role') ||
      {A: 'link', BUTTON: 'button', INPUT: 'input', SELECT: 'select',
       TEXTAREA: 'textarea', TH: 'columnheader', SUMMARY: 'disclosure'}[el.tagName] ||
      el.tagName.toLowerCase();
    const rec = {ref: refFor(el), role, name};
    if (r === 0) rec.in_region = true;
    // Which table a header belongs to matters: an article can carry several sortable
    // tables whose header texts overlap.
    if (el.tagName === 'TH') {
      const tbl = el.closest('table');
      rec.table = tbl ? (tbl.id || tbl.getAttribute('data-agent-ref') || null) : null;
      rec.column_index = el.cellIndex;
    }
    if (el.tagName === 'A') rec.href = (el.getAttribute('href') || '').slice(0, 120);
    if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') {
      rec.type = el.type || null; rec.name_attr = el.name || null;
      // Without the current value a planner cannot tell a filled field from an empty one,
      // and will propose filling it again for as long as its budget lasts.
      rec.value = norm(el.value || '').slice(0, 60);
    }
    const st = [];
    if (/headerSortUp/.test(el.className || '')) st.push('sorted-ascending');
    if (/headerSortDown/.test(el.className || '')) st.push('sorted-descending');
    const ae = el.getAttribute('aria-expanded');
    if (ae !== null) st.push('expanded=' + ae);
    if (el.disabled) st.push('disabled');
    if (st.length) rec.state = st;
    interactive.push(rec);
  }

  bump('non_interactive_nodes',
       document.querySelectorAll('*').length - interactive.length - regions.length);
  bump('script_style_nodes',
       document.querySelectorAll('script, style, link, meta, noscript').length);

  return {
    rule_version: null,
    url: location.href,
    title: norm(document.title),
    interactive,
    anchor_regions: regions,
    dropped,
    full_dom_chars: document.documentElement.outerHTML.length,
    rendered_text_chars: norm(document.body.innerText).length,
  };
}
"""

DEFAULTS = {"maxInteractive": 60, "maxAnchorRegions": 4, "maxRowsPerRegion": 6}


async def reduce_page(page, terms, **overrides) -> dict[str, Any]:
    """The reduced view, plus what it cost to produce it."""
    args = {**DEFAULTS, **overrides, "terms": [t for t in terms if t]}
    view = await page.evaluate(REDUCE_JS, args)
    view["rule_version"] = RULE_VERSION
    view["limits"] = args
    return view


def reduction_record(view: dict[str, Any], artifact_id: str | None) -> dict[str, Any]:
    """What A7.3 requires in the trace: the rule version, what was dropped by category, and
    a reference to the full artifact the reduced view came from."""
    return {
        "rule_version": view.get("rule_version"),
        "dropped": view.get("dropped", {}),
        "kept": {
            "interactive": len(view.get("interactive", [])),
            "anchor_regions": len(view.get("anchor_regions", [])),
        },
        "full_dom_chars": view.get("full_dom_chars"),
        "rendered_text_chars": view.get("rendered_text_chars"),
        "full_artifact_id": artifact_id,
    }

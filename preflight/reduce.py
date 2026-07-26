"""Snapshot reduction, rule version `reduce/v0.2-preflight`.

Produces the bounded view of a page that a model call is allowed to see: interactive
elements, the region around candidate anchors, and nothing else. Raw snapshots are never
sent to a model, and verification never runs against this output — it runs against the
full stored artifact.

Reduction is goal-scoped, not document-order-scoped. v0.1 filled its whole element budget
with Wikipedia's navigation chrome and dropped the sort headers the task needed, so
candidate anchor regions are resolved first and interactive elements are ranked by their
distance from those regions.

This is the M0 measurement version. It exists so token and cost numbers come from a
realistic reduced view instead of an estimate; the production reducer will carry a new
version identifier.
"""

RULE_VERSION = "reduce/v0.2-preflight"

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


def reduce_page(page, terms, **overrides):
    args = {**DEFAULTS, **overrides, "terms": list(terms)}
    view = page.evaluate(REDUCE_JS, args)
    view["rule_version"] = RULE_VERSION
    return view

"""One definition of what durably identifies an element, shared by everything that needs it.

Three parts of the system have to agree on "the same element": the reducer describes elements
to the model, the executor resolves the ref the model answers with back into something that
outlives the ref, and the verifier checks the trace against the target a postcondition
declared before browsing. Each carried its own list of fields, and nothing made those lists
agree.

They disagreed three times. At M2 it was the DOM id and the `name` attribute; at M3 the
visible text; at OP-7 the `href` and the `title`. Every time the symptom was identical — a
run that took exactly the right action, scored as having skipped it — and every time the fix
was to append one more field to one more list. That is a treatment, not a cure: the end of
that road is a real site whose elements carry a handle none of the three lists happens to
have, on a day when nobody is looking.

So identity is defined once, here:

- `FIELDS` is the list, and it is the only list.
- `COLLECT_JS` gathers exactly those fields in the browser. It is the only such expression in
  the codebase; the reducer and the executor both evaluate it rather than each writing their
  own.
- `ElementIdentity` holds them, and `match()` is the single comparison. A declared target, a
  planner-proposed ref and a scripted CSS selector are all resolved through it, so "did this
  action happen" has one answer rather than three.

The comparison is whole-token rather than substring. `target in haystack` over a joined blob
credited a required action whenever the target happened to appear anywhere inside anything —
loose in the direction that matters, because a false positive here marks a declared action as
performed when it was not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Every durable handle a page offers for one element. Adding a way to name an element means
#: adding it here, once; `test_the_collector_and_the_dataclass_cannot_drift` fails if the
#: browser-side collector and this list stop agreeing.
FIELDS: tuple[str, ...] = (
    "tag",      # element type
    "role",     # explicit ARIA role, when the markup declares one
    "id",       # DOM id — what a CSS selector in a postcondition usually names
    "name",     # the `name` attribute, which is how form controls are addressed
    "label",    # accessible name: aria-label, associated <label>, or alt text
    "text",     # visible text, or the current value when there is no text
    "href",     # a link's declared target; often the only stable handle on a real site
    "title",    # the title attribute
    "testid",   # data-testid / data-test / data-qa, when a site publishes one
)

#: The one browser-side collector. Evaluated with an element as `el`.
COLLECT_JS = r"""
(el) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().slice(0, 120) || null;
  return {
    tag: el.tagName ? el.tagName.toLowerCase() : null,
    role: el.getAttribute('role') || null,
    id: el.id || null,
    name: el.getAttribute('name') || null,
    label: norm(el.getAttribute('aria-label') ||
                (el.labels && el.labels[0] && el.labels[0].innerText) ||
                el.getAttribute('alt') || ''),
    text: norm(el.innerText || (el.value === undefined ? '' : String(el.value))),
    href: el.getAttribute('href') || null,
    title: el.getAttribute('title') || null,
    testid: el.getAttribute('data-testid') || el.getAttribute('data-test') ||
            el.getAttribute('data-qa') || null,
  };
}
"""

_WORD = re.compile(r"[a-z0-9]+")


def normalise(text: str | None) -> str:
    """Reduce a handle to whole words, so that matching cannot land mid-token.

    `#next`, `li.next a` and `Next page` all normalise to word sequences containing `next`;
    `resort` does not contain the word `sort`.
    """
    return " ".join(_WORD.findall((text or "").lower()))


@dataclass(frozen=True)
class ElementIdentity:
    """What one element answers to. Absent fields are `None`, never guessed."""

    tag: str | None = None
    role: str | None = None
    id: str | None = None
    name: str | None = None
    label: str | None = None
    text: str | None = None
    href: str | None = None
    title: str | None = None
    testid: str | None = None
    #: Where the element was named from when identity could not be collected directly — a
    #: scripted CSS selector, or the step's own summary. Kept separate from the collected
    #: fields so a match on it is visible as the weaker evidence it is.
    recorded_as: tuple[str, ...] = ()
    #: The transient handle the reducer stamped on the element for one model call. Not part
    #: of identity: it is meaningless on the next page load, which is the whole problem.
    ref: str | None = None
    resolved: bool = True

    @classmethod
    def from_browser(cls, collected: dict[str, Any], *, ref: str | None = None
                     ) -> "ElementIdentity":
        return cls(**{f: collected.get(f) for f in FIELDS}, ref=ref)

    @classmethod
    def from_trace(cls, detail: dict[str, Any], summary: str = "") -> "ElementIdentity":
        """Rebuild identity from what a trace entry recorded.

        A scripted step names a CSS selector rather than resolving an element, so the
        selector and the summary are carried as `recorded_as`: still matched, through the
        same comparison, but distinguishable from a handle the page actually published.
        """
        element = detail.get("element") or {}
        weak = tuple(str(x) for x in (detail.get("selector") or "", summary) if x)
        return cls(**{f: element.get(f) for f in FIELDS},
                   recorded_as=weak, ref=element.get("ref"),
                   resolved=bool(element.get("resolved", bool(element))))

    def to_dict(self) -> dict[str, Any]:
        """Only what is actually known — a view full of nulls costs tokens and says nothing."""
        out = {f: getattr(self, f) for f in FIELDS if getattr(self, f)}
        if self.ref:
            out["ref"] = self.ref
        if not self.resolved:
            out["resolved"] = False
        return out

    def match(self, target: str) -> str | None:
        """The field `target` names this element by, or None.

        Returns the field rather than a bool so the trace can record *how* an element was
        recognised: a match on `href` and a match on the step's own summary are different
        strengths of evidence and should not read the same afterwards.
        """
        wanted = normalise(target.lstrip("#."))
        if not wanted:
            return None
        needle = f" {wanted} "
        for field_name in FIELDS:
            value = getattr(self, field_name)
            if value and needle in f" {normalise(str(value))} ":
                return field_name
        for recorded in self.recorded_as:
            if needle in f" {normalise(recorded)} ":
                return "recorded_as"
        return None

    def matches(self, target: str) -> bool:
        return self.match(target) is not None

    def selector(self) -> str:
        """A CSS selector for this element that survives the ref being restamped."""
        if self.id:
            return f"#{self.id}"
        if self.name:
            return f"[name={self.name!r}]"
        if self.testid:
            return f"[data-testid={self.testid!r}]"
        return f"[data-agent-ref='{self.ref}']" if self.ref else ""


async def identify(page, ref: str) -> ElementIdentity:
    """Resolve a ref to identity. Never raises: failing to identify must not fail an action."""
    if not ref:
        return ElementIdentity(resolved=False)
    try:
        handle = await page.query_selector(f"[data-agent-ref='{ref}']")
        if handle is None:
            return ElementIdentity(ref=ref, resolved=False)
        collected = await handle.evaluate(COLLECT_JS)
    except Exception:  # noqa: BLE001 - identification is diagnostic, not load-bearing
        return ElementIdentity(ref=ref, resolved=False)
    return ElementIdentity.from_browser(collected, ref=ref)

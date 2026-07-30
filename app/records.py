"""What is promised, and which site a task named (A17.1, A17.2).

This module exists so that two things stop sharing a home. Deciding *where a run goes* is
routing; deciding *whether the evidence came from where the task said* is verification, and
§4 exists because the second must not be performed by the code that did the first. Both need
the same two facts — the promised records, and the site a task names in words — so the facts
live here and neither side owns them.

The site a task names is read from the task text alone: a URL if it carries one, the host
otherwise, and failing both a common name ("Wikipedia") mapped to the host that serves it.
Nobody writes `en.wikipedia.org` in a sentence, and matching only hostnames is what let a
task about Wikipedia look like a task naming no site — and be answered by our own fixture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

#: A URL written into a task. A trailing bracket belongs to the URL when the URL opened it —
#: Wikipedia titles carry them — so it is kept rather than trimmed into a 404.
URL_IN_TASK = re.compile(r"https?://(?:[^\s,;\"']|\([^\s,;\"')]*\))+")
HOST_IN_TASK = re.compile(
    r"\b((?:[a-z0-9][a-z0-9-]*\.)+(?:com|org|net|edu|gov|int|io|ai|co|dev|info|me|"
    r"uk|de|fr|jp|tw|cn|eu))\b(/[^\s,;\"')]*[^\s,;\"')?.!])?")


@dataclass(frozen=True)
class PromisedRecord:
    """A promised `site × operation` record (S-1.3), keyed by the route that serves it.

    This is the single list. Admission reads it to decide `T-DECLARED`, and the support
    page renders it, so the page cannot claim a record the router cannot reach — which is
    how the page came to advertise four unimplemented operations after they shipped.
    """

    id: str
    site: str
    operation: str
    route: str
    #: Further routes belonging to this record. A cross-behaviour from §3.3 is not a record
    #: of its own — XB-1's proof of absence over a category listing is a list-level fact
    #: about that category, reached by the same navigation and proven by the same
    #: enumeration, so it is part of OP-6 rather than a fifth promise.
    extra_routes: tuple[str, ...] = ()
    #: How far the record reaches, when the operation line above is broader than the build.
    #: Rendered beside the status badge, because an unqualified `implemented` next to an
    #: operation with a known hole is the support matrix advertising breadth its own
    #: limitations list denies. Every qualifier names the entry that reproduces it.
    qualified: str = ""


PROMISED_RECORDS: tuple[PromisedRecord, ...] = (
    PromisedRecord("OP-4", "en.wikipedia.org",
                   "Sort a sortable table by a named column, read a cell from the top row",
                   "wiki_sort"),
    PromisedRecord("OP-5", "en.wikipedia.org",
                   "Expand a collapsed box and extract a value not visible beforehand",
                   "wiki_expand",
                   qualified="Named values only. \"tell me its Hardware group\" is verified; "
                             "the ordinal form \"tell me the label of its first row group\" "
                             "abstains, because the label itself is what was asked for and "
                             "no anchor can be frozen for a value nobody has named yet. "
                             "L-8 below runs both halves."),
    PromisedRecord("OP-6", "books.toscrape.com",
                   "Category navigation and pagination, list-level facts", "book_category",
                   extra_routes=("book_absence",)),
    PromisedRecord("OP-7", "books.toscrape.com",
                   "Open a product page and extract a labelled field", "book_detail"),
)

#: Routes that are not capabilities but policy demonstrations on a promised site. They must
#: stay reachable there: a robots refusal that can only be shown on a site we wrote is not a
#: demonstration of anything, and restricting a named site to its promised operations alone
#: made the refusal unreachable on the site whose rule it is.
POLICY_ROUTES: dict[str, tuple[str, ...]] = {
    "en.wikipedia.org": ("wiki_special",),
}

RECORD_BY_ROUTE: dict[str, PromisedRecord] = {
    route: record for record in PROMISED_RECORDS
    for route in (record.route, *record.extra_routes)
}


@dataclass(frozen=True)
class GateOperation:
    """A fixture operation that exists to prove a mechanism, not to promise a capability.

    Withdrawn from the promised set by A1.2 and kept as gate evidence: each one is
    constructed so the answer cannot be reached without performing the UI action, which is
    what makes "the action was necessary" checkable rather than declared.
    """

    id: str
    route: str
    mechanism: str
    shortcut_proof_because: str


GATE_OPERATIONS: tuple[GateOperation, ...] = (
    GateOperation("GS-1", "search", "POST-only form search",
                  "Results exist only behind a POST. No URL expresses a result set, and "
                  "the fixture answers GET /search with 405, so the form must be filled "
                  "and submitted."),
    GateOperation("GS-2", "paginate", "Client-side pagination with no URL change",
                  "The URL is identical on every page, so page N cannot be reached by "
                  "navigating to it — only by clicking through."),
    GateOperation("GS-3", "overlay", "Overlay dismissal, then the underlying action",
                  "The control beneath is disabled until the overlay is dismissed, so a "
                  "run that skips the dismissal cannot perform the action at all."),
)


def host_key(host: str) -> str:
    """One spelling of a host, so `www.` cannot make one site look like two."""
    return (host or "").lower().removeprefix("www.")


def resolve_entry(task: str) -> str:
    """Where a task says to start, or "" if it never says.

    Not being able to resolve one is a real outcome with its own explanation, not a
    fallback to guessing a search engine — picking a starting page the task never named is
    how a run ends up answering a question nobody asked.
    """
    explicit = URL_IN_TASK.search(task)
    if explicit:
        return explicit.group(0).rstrip(".,;:'\"")
    host = HOST_IN_TASK.search(task.lower())
    if host:
        return f"https://{host.group(1)}{host.group(2) or '/'}"
    return ""


def fixture_host() -> str:
    from app.config import settings

    return host_key(urlsplit(settings.fixture_base_url).netloc)


#: The Chinese names of the promised sites (A19.4). The graders' own assignment ships in
#: Traditional Chinese, so assuming an English spelling is a guess we do not have to make.
#: `books.toscrape.com` has no Chinese name — its name is the domain, which already
#: matches — so only Wikipedia has entries here.
CHINESE_SITE_ALIASES: dict[str, str] = {
    "維基百科": "en.wikipedia.org",
    "维基百科": "en.wikipedia.org",
    "維基": "en.wikipedia.org",
    "维基": "en.wikipedia.org",
}


def site_aliases() -> dict[str, str]:
    """The bare names people use for the sites we serve, mapped to their hosts."""
    aliases: dict[str, str] = {}
    for record in PROMISED_RECORDS:
        host = host_key(record.site)
        aliases[host] = host
        labels = host.split(".")
        if len(labels) >= 2:
            aliases[labels[-2]] = host
    aliases.update(CHINESE_SITE_ALIASES)
    # The fixture is not a promised record and never appears in the support matrix, but a
    # task can still name it, and naming it is now the only way to reach it (A24.4). Its
    # host is whatever the deployment configured, so the word is what a person can write.
    aliases.setdefault("fixture", fixture_host())
    aliases.setdefault(fixture_host(), fixture_host())
    return aliases


def named_site(task: str) -> str:
    """The host this task names, normalised, or "" if it names none."""
    entry = resolve_entry(task)
    if entry:
        return host_key(urlsplit(entry).netloc)
    low = task.lower()
    for alias, host in site_aliases().items():
        if alias.isascii():
            # `(?<!\w)` rather than `\b`: "Wikipedia's" must match, "unwikipedia" must not.
            if re.search(rf"(?<!\w){re.escape(alias)}\b", low):
                return host
        # Chinese is written without spaces and every CJK character is a word character,
        # so `\b` never fires between 「維基百科」 and the 「的」 that follows it — the
        # alias table would be there and match nothing. A substring is the boundary.
        elif alias in low:
            return host
    return ""

# Task 2 Seam — Filing Acquisition Contract v1.0

**Standalone document.** You do not need to read the Task 1 spec to consume this. Nothing here
depends on browser plans, locators, agent traces, or any Task 1 internal concept — by design.

**What this is:** the interface where Task 1 (acquisition) hands off to Task 2 (10-K item
extraction). Task 1 gets the bytes and proves what it got. Task 2 decides what the bytes mean.

**Status:** frozen as a contract. Field names below are normative; the wire encoding (JSON shape,
transport, storage location) is chosen by the engineering session and documented alongside the
implementation.

---

## 1. Division of responsibility

| Task 1 owns | Task 2 owns |
|---|---|
| Identifying a filing unambiguously | Everything about document structure |
| Retrieving bytes exactly as served | Item 1–16 segmentation, Part I–IV mapping |
| Recording provenance and integrity (hash, length, media type, time) | Extraction confidence, format-variance handling |
| Declaring what it did **not** retrieve | Interpreting content |

**Task 1 MUST NOT** contain any 10-K-specific logic — no item taxonomy, no heading heuristics, no
segmentation. If document-structure knowledge appears on the Task 1 side, the seam is broken.

---

## 2. Identifying a filing

A filing is identified by the pair:

- `cik` — the SEC Central Index Key of the filer, zero-padded to 10 digits.
- `accession_number` — the SEC accession number of the submission.

These two together are unique and stable. Consumers address filings by this pair; they never need a
URL, a search query, or anything Task 1 did to find it.

Task 1 accepts either the pair directly, or a lookup input (company identifier + form type +
period/date) which it resolves to the pair using SEC's documented data APIs. **If the lookup is
ambiguous, Task 1 returns the candidate set and does not guess.** An arbitrary tie-break here would
be exactly the kind of silent failure both tasks exist to prevent.

---

## 3. What gets retrieved

Three levels, deliberately different:

### 3.1 Fully retrieved (bytes + integrity) — always

1. **Primary document** — the main 10-K document of the submission.
2. **Complete submission text file** — the single file containing the full submission.

For each of these, Task 1 MUST provide:

| Field | Meaning |
|---|---|
| `role` | `primary_document` or `complete_submission` |
| `filename` | Filename as listed in the filing's own index |
| `source_url` | The exact URL fetched |
| `retrieved_at` | UTC timestamp of retrieval |
| `byte_length` | Length in bytes of what was stored |
| `media_type` | Content type as served |
| `sha256` | SHA-256 of the stored bytes |
| `storage_ref` | How the consumer obtains the bytes |
| `retrieval_status` | `complete` \| `not_retrieved` (see §4) |

**Bytes are stored exactly as served.** No normalisation, re-encoding, whitespace cleanup, or
HTML-to-text conversion is applied to these two representations. `sha256` is computed over the stored
bytes so a consumer can verify integrity independently.

### 3.2 Inventory only (metadata, no bytes)

Every other representation in the submission — exhibits, XBRL instance and taxonomy files, images,
graphics — appears in the inventory with `filename`, `role`/type as listed by the filing index,
`media_type`, and size as reported by the index. **No bytes are fetched and no hash is computed for
these.** The inventory is complete: every item the filing index lists is present in it, marked
`inventory_only`.

If Task 2 later needs an exhibit's bytes, that is a new requirement for Task 1, not something Task 2
should work around by fetching on its own.

### 3.3 Never

Anything not part of the identified submission.

---

## 4. Caps and the prohibition on silent truncation

The complete submission text file can be very large. Task 1 enforces a configurable size cap.

**If a representation exceeds the cap, it is NOT stored and NOT hashed.** It is recorded with:

- `retrieval_status: "not_retrieved"`
- `not_retrieved_reason` — e.g. `exceeds_size_cap`, `fetch_failed`, `unavailable_at_source`
- `cap_bytes` — the cap in force at the time
- `reported_size_bytes` — the size reported by the source, when known

**Partial content is never stored under a `complete` status. Truncation without saying so is
prohibited** — a downstream extractor that silently receives half a document produces plausible,
wrong output, which is the exact failure mode this design targets.

A consumer MUST check `retrieval_status` before using bytes. `sha256` is present only when
`retrieval_status` is `complete`.

---

## 5. Access policy Task 1 applies

Recorded here so Task 2 inherits the same posture and does not accidentally undo it.

- Retrieval uses SEC's explicitly permitted archive path (`/Archives/edgar/data`, `Allow`-ed in
  `sec.gov/robots.txt`) and SEC's documented JSON APIs on `data.sec.gov`. The `cgi-bin` browse
  interface is `Disallow`-ed and is not used.
- Every request declares a `User-Agent` containing a real contact address, plus
  `Accept-Encoding: gzip, deflate`, per SEC's published requirement.
- Self-imposed rate limit: **≤ 1 request/second**. SEC's published cap is 10 requests/second; we stay
  an order of magnitude under it.
- **Targeted retrieval only.** No enumeration, no crawling, no bulk download. SEC states it does not
  allow automated tools to crawl the site; the seam fetches only what a specific user request needs.

Sources: `https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data`,
`https://www.sec.gov/robots.txt` (verified 2026-07-26).

---

## 6. What Task 2 must not assume

- **Not that a retrieval succeeded.** Always read `retrieval_status`.
- **Not that bytes are text.** `media_type` is what the source served; encoding detection is Task 2's
  problem.
- **Not that the primary document is HTML.** Older and unusual filings vary.
- **Not that the inventory implies availability.** Inventory entries carry no bytes by definition.
- **Not that content has been cleaned.** Nothing has been normalised.
- **Not that re-fetching is free or permitted.** Use `storage_ref`; do not re-crawl SEC from Task 2.

---

## 7. Independent-consumer test

The seam is validated by a program written **against this document only**. That program:

1. Takes a company identifier and form type, or a `(cik, accession_number)` pair.
2. Obtains the acquisition record through the seam's public interface.
3. Verifies both fully-retrieved representations have `byte_length`, `media_type`, `sha256`, and
   `retrieved_at`, and that recomputing SHA-256 over the fetched bytes matches.
4. Confirms the inventory lists every item in the filing index, each marked `inventory_only`.
5. Forces the cap and confirms the oversized representation is marked `not_retrieved` with a reason,
   with no bytes and no hash.

It MUST NOT import Task 1 internal modules. If it needs to, this document is incomplete — fix the
document.

---

## 8. Deliberately out of scope for v1.0

No item schema. No content parsing. No cross-filing normalisation. No historical backfill. No
exhibit byte retrieval. These are Task 2 decisions and are not pre-empted here.

# Task 2 Seam — Filing Acquisition Contract v1.1

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

- `target_registrant_cik` — the SEC Central Index Key of the **registrant the filing is about**,
  zero-padded to 10 digits.
- `accession_number` — the SEC accession number of the submission.

These two together are unique and stable. Consumers address filings by this pair; they never need a
URL, a search query, or anything Task 1 did to find it.

### 2.1 Three CIKs, and why they are not interchangeable

The first ten digits of an accession number identify the **submitting** CIK, which may be a filing
agent rather than the company. The archive path uses a third form (no leading zeros). A submission may
also disclose co-registrants.

| Field | Meaning |
|---|---|
| `target_registrant_cik` | The registrant the filing is about. **This is the filing's identity.** |
| `submitter_cik_from_accession` | Derived from the accession prefix. May be an agent. |
| `archive_cik` | The form used in the `/Archives/edgar/data/{cik}/` path. |
| `registrants[]` | Every registrant disclosed by SEC metadata, each with a `role`. |

Task 1 preserves all of these separately and reconciles them against SEC metadata. **Assuming the
accession prefix is the company is a silent wrong answer for agent-submitted and multi-registrant
filings.**

If an accession alone does not resolve to exactly one registrant, Task 1 returns
`needs_registrant_cik` rather than assuming.

### 2.2 Lookup, `as_of`, and revision policy

Task 1 accepts either the identifying pair directly, or a lookup input (company identifier + form
type + period) which it resolves using SEC's documented data APIs. **If the lookup is ambiguous, Task
1 returns the candidate set and does not guess.** An arbitrary tie-break here would be exactly the
kind of silent failure both tasks exist to prevent.

Every lookup carries:

- `as_of` — an immutable reproducibility cutoff. Task 1 MUST NOT select a filing or amendment
  accepted after it. Without this, "the FY2025 10-K" silently changes meaning the day an amendment is
  accepted.
- `revision_policy` — `exact_accession`, `original`, or `consolidated_as_of`.

`form_type` is matched exactly. `10-K/A` is an **amendment relationship**, never an implicit
equivalent of `10-K`, and **an amendment is an overlay, not an assumed replacement** of the original
filing.

### 2.3 Four dates, none inferred from another

| Field | Meaning |
|---|---|
| `report_period_end` | The fiscal period the filing covers |
| `filing_date` | The official filing date |
| `accepted_at` | SEC's acceptance timestamp |
| `retrieved_at` | When this system fetched a representation |

A missing date is never derived from a different one, and fiscal year means the year of the report
period — not the year of submission.

---

## 3. What gets retrieved

Three levels, deliberately different:

### 3.1 Fully retrieved (bytes + integrity) — always

1. **Primary document** — the main 10-K document of the submission.
2. **Complete submission text file** — the single file containing the full submission.
3. **The resolution snapshots** — the SEC submissions JSON, the filing index, and the archive
   directory index that were used to resolve this filing. They are stored and hashed like any other
   representation. Without them, *"why this accession?"* cannot be answered after the fact, which
   makes the resolution itself unverified.

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
HTML-to-text conversion is applied. `sha256` is computed over the stored bytes so a consumer can
verify integrity independently.

### 3.1a Raw and derived representations

A document may carry more than one representation. Each has its own identity, `sha256` and
`retrieved_at`.

- A **derived** representation (normalised text, a DOM snapshot) MUST name the representation it came
  from and the transform's name and version, and **MUST NOT overwrite the raw bytes**.
- If the same URL later serves different bytes, that is a **new representation with a new hash**. The
  earlier one remains valid and addressable. **The URL is provenance, not identity.**

Task 1 v1.1 produces no derived representations of its own; the rule exists so that adding one later
cannot destroy the original.

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

### 4.1 Metadata visibility is not availability

A filing can appear in SEC metadata before every archive object is actually retrievable. Task 1 may
retry within a bounded budget, but **an acquisition MUST NOT be reported as complete on the strength
of metadata alone** when a mandatory representation is missing. It terminates as partial or failed,
with `pending_source_publication` as the reason.

## 4b. Relationships between filings

Task 1 records, **from SEC metadata only**:

| Relationship | Meaning |
|---|---|
| `amends` / `amended_by` | Between a `10-K` and a `10-K/A`, each keeping its own accession |
| `related_filing` | Another filing by the same registrant that metadata associates with this one |

Each relationship records the `as_of` cutoff in force. An amendment is an **overlay**; Task 2 applies
it as such and MUST NOT treat a `10-K/A` as a replacement for the original filing.

**`incorporates_by_reference` is deliberately not a Task 1 output.** Detecting that Part III is
incorporated from a proxy statement means reading incorporation language inside the filing — document
structure, which is Task 2's side of the seam (§1). What Task 1 guarantees instead is that the
inventory and relationships are complete enough for Task 2 to represent an Item as *incorporated by
reference* rather than *missing*, without fabricating text. Items 10–14 being absent from the primary
document is a normal, correct outcome.

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

6. Resolves a filing whose **submitting CIK differs from the target registrant** and confirms the
   three CIK forms are recorded separately (§2.1).
7. Runs a period lookup with an `as_of` earlier than a known `10-K/A`'s acceptance, and confirms the
   original filing is returned with the amendment recorded as a relationship, not substituted (§2.2,
   §4b).
8. Submits an ambiguous company name and confirms a candidate set comes back, not a choice.

It MUST NOT import Task 1 internal modules. If it needs to, this document is incomplete — fix the
document. **This rule binds the conformance test, not a Task 2 product** — a Task 2 build may reuse
Task 1's store, run model and frontend.

---

## 8. Deliberately out of scope for v1.1

No item schema. No content parsing. No cross-filing normalisation. No historical backfill. No
exhibit byte retrieval. These are Task 2 decisions and are not pre-empted here.

---

## 9. Changelog

### v1.1 (2026-07-28)

Adopted from the product owner's `Q1_Q2_SEC_FILING_CONTRACT.md` proposal, recorded as Amendment 16 of
the Task 1 spec. Every change fixes a case where v1.0 would have produced a **confident wrong
answer**, not a missing convenience:

- **§2.1** three CIK forms preserved separately; the target registrant is the identity; an accession
  that does not resolve to one registrant returns `needs_registrant_cik`.
- **§2.2** `as_of` cutoff and explicit revision policy; an amendment is an overlay, never a
  replacement.
- **§2.3** four separate dates, none inferred from another.
- **§3.1** the resolution snapshots are retained and hashed.
- **§3.1a** raw vs derived representations; raw bytes are immutable; changed bytes at a stable URL
  produce a new representation.
- **§4.1** metadata visibility never equals availability.
- **§4b** amendment relationships from SEC metadata; `incorporates_by_reference` explicitly left to
  Task 2.
- **§7** three added conformance cases; the internal-module rule clarified as binding the test, not a
  Task 2 product.

**Deliberately not adopted**, so their absence is a decision rather than an oversight: a 2 rps rate
limit (our ≤ 1 rps stands); capability-token authorisation, signed content URLs and a separate 7-day
retention rule (no auth system exists, and retention is governed by the Task 1 deployment policy — a
second conflicting rule would be a trap); an "extended" profile that eagerly fetches every textual
document and resolves related filings (close to SEC's prohibition on enumeration, and it buys a first
Task 2 build nothing); and a Task 1-emitted evidence/locator object (text offsets into a 10-K are
Task 2's coordinate system — Task 1 guarantees stable document and representation identifiers plus
hashes, and Task 2 builds locators on those without altering them).

Future coverage, not required for v1.1: legacy text and malformed-HTML filings, PDF-primary filings,
the large-complete-submission budget boundary, and the authorisation cases that arrive with an auth
system.

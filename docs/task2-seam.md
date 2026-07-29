# Task 2 Seam — Filing Acquisition Contract v1.2

**Standalone document.** You do not need to read the Task 1 spec to consume this. Nothing here
depends on browser plans, locators, agent traces, or any Task 1 internal concept — by design.

> ## ⚠️ Read this before anything else: there is no producer
>
> **Task 1 was built, submitted, and it does not acquire SEC filings.** It is a general browser
> automation agent, and the four operations it promises are on `en.wikipedia.org` and
> `books.toscrape.com`. **No code in this repository emits an acquisition bundle. Nothing will hand
> you one.**
>
> v1.1 of this document was written as a handoff between two halves of one system, on the assumption
> that the acquisition half would exist. It did not get built — that was a deliberate cut with two
> days left, recorded as one, not a gap discovered later.
>
> **So this document changes role rather than content.** It is no longer *the interface you consume*.
> It is **the contract you build to** — the shape of the acquisition layer Task 2 must produce for
> itself before any extraction can be trusted. Every requirement below still holds; what changed is
> who satisfies it. Wherever the text says *"Task 1 MUST"*, read *"your acquisition layer MUST"*, and
> wherever it says *"Task 1 guarantees"*, read *"you will have to guarantee"*.
>
> Two things follow immediately, and they are the reason this framing is worth keeping rather than
> deleting:
>
> - **§1's separation is still the right design**, and now it is a separation inside one codebase.
>   Acquisition must not know what a 10-K Item is; extraction must not fetch. Collapsing the two is
>   how an extractor comes to re-fetch a page mid-parse and produce a result nobody can reproduce.
> - **§10 said "never fetch from SEC yourself." That prohibition is now void** and is the one clause
>   that inverts: fetching is yours. What survives from it is the *reason* it existed — one fetch,
>   hashed, recorded, and never silently repeated.
>
> §14 lists what Task 1 actually built that is worth reusing, and what you now have to build that
> this document assumed you would be given.

**Status:** normative as a build target. Field names and status values below are binding on whatever
produces bundles. This is the only contract document — any proposal or design note elsewhere in the
repository is an input to it, not a second source of truth.

**Version:** `acquisition-bundle/1.2`, profile `sec-10k/1.2`. See §13 for the changelog.

---

## 0. If you are starting Task 2, read this first

This document is sufficient on its own. You do not need the Task 1 spec, its code, or its history.

**What you are inheriting.** A schema and a set of obligations — not bytes, and not a service. You
will build the acquisition layer yourself, to the shape below: the filing resolved to one registrant
and one accession, the primary document and the complete submission text fetched byte-for-byte and
hashed, the resolution evidence preserved, and everything *not* fetched saying so explicitly. Build
it as a separate stage with its own output artifact, so that the extractor consumes stored bytes and
never a live fetch.

**What is yours.** Everything about what the bytes mean: Item 1–16 segmentation, Part I–IV mapping,
format-variance handling, extraction confidence, your own evaluation set, and your own frontend.
Task 2 carries the same submission obligations Task 1 does — a publicly operable web frontend, a
self-built evaluation set, an honest list of what works and what does not with concrete examples, and
an analysis of performance, cost, scalability and correctness verification.

**Three things that will shape your design more than anything else here:**

1. **A missing Item is often correct, not a failure.** Items 10–14 are routinely incorporated by
   reference from a proxy statement; Item 6 is reserved; Item 16 is optional. Plan for an Item status
   of at least `present` | `reserved` | `optional_absent` | `incorporated_by_reference`, and treat
   emitting text for an Item that is not there as the worst outcome available to you. Task 1
   guarantees the inventory and relationships are complete enough that you can reach
   `incorporated_by_reference` **without guessing** (§4.7) — but Task 1 will never tell you an Item
   *is* incorporated, because reading incorporation language is document structure, which is yours.
2. **The complete submission text is your recovery path.** When the primary document is malformed,
   truncated by its own filer, or structured unusually, the complete submission file contains the
   disseminated package including headers. It is always fetched (§5.1) for exactly this reason.
3. **Bytes are not permanent, identity is.** Retention is governed by the Task 1 deployment policy,
   not by this contract. Expiry is a **recorded, dated state** that keeps all metadata (§9), so a
   bundle stays auditable after its bytes are gone — but if you need the bytes long-term, copy them
   into your own content-addressed store. Reacquisition produces **new** identifiers and hashes; a
   deleted artifact is never silently rebuilt under its old ID.

**What you must not do:** let the extractor fetch (fetching belongs to the acquisition stage and
happens once, §5), rebuild a hash or an identifier after the fact (§13), or treat any bundle that is
not `verified` as usable input to extraction (§7.1). The old prohibition on fetching from SEC at all
is void — see the notice above.

---

## 1. Division of responsibility

| Task 1 owns | Task 2 owns |
|---|---|
| Resolving which filing is meant, unambiguously | Everything about document structure |
| Retrieving bytes exactly as served | Item 1–16 segmentation, Part I–IV mapping |
| Recording provenance and integrity (hash, length, media type, times) | Extraction confidence, format-variance handling |
| Declaring what it did **not** retrieve, and why | Interpreting content |
| Recording filing relationships visible in SEC metadata | Deciding whether an Item is absent or incorporated by reference |

**Task 1 MUST NOT** contain any 10-K-specific logic — no item taxonomy, no heading heuristics, no
segmentation, no reading of incorporation language. If document-structure knowledge appears on the
Task 1 side, the seam is broken.

**Task 2 MUST NOT** depend on Task 1's browser trace, locator strategy, prompts, model output, or UI.

---

## 2. Identity

### 2.1 A filing is identified by two fields

- `target_registrant_cik` — the SEC Central Index Key of the **registrant the filing is about**,
  zero-padded to 10 digits.
- `accession_number` — the accession number of the submission, dashed form,
  matching `^\d{10}-\d{2}-\d{6}$`.

Consumers address filings by this pair. They never need a URL, a search query, or anything Task 1 did
to find it.

### 2.2 Three CIKs, and why they are not interchangeable

The first ten digits of an accession number identify the **submitting** CIK, which may be a filing
agent rather than the company. The archive path uses a third form (leading zeros stripped). A
submission may also disclose co-registrants.

| Field | Meaning |
|---|---|
| `target_registrant_cik` | The registrant the filing is about. **This is the filing's identity.** |
| `submitter_cik_from_accession` | Derived from the accession prefix. May be a filing agent. |
| `archive_cik` | The form used in `/Archives/edgar/data/{archive_cik}/`. |
| `registrants[]` | Every registrant disclosed by SEC metadata, each with `cik`, `name`, `role`. |

Task 1 preserves all of these separately and reconciles them against SEC metadata. **Assuming the
accession prefix is the company is a silent wrong answer** for agent-submitted and multi-registrant
filings.

If an accession alone does not resolve to exactly one registrant, Task 1 returns
`needs_registrant_cik` rather than assuming.

### 2.3 Four dates, none inferred from another

| Field | Meaning |
|---|---|
| `report_period_end` | The fiscal period the filing covers (SEC "Period of Report") |
| `filing_date` | The official filing date |
| `accepted_at` | SEC's acceptance timestamp |
| `retrieved_at` | When this system fetched a given representation |

A missing date is never derived from a different one. **Fiscal year means the year of the report
period**, not the year of submission.

---

## 3. Request

### 3.1 Shape

```json
{
  "schema_version": "sec-10k-acquisition-request/1.1",
  "target": {
    "registrant_cik": "0000320193",
    "ticker": "AAPL",
    "name": null
  },
  "selector": {
    "kind": "period",
    "accession_number": null,
    "sec_url": null,
    "form_type": "10-K",
    "report_period_end": null,
    "fiscal_year": 2025
  },
  "revision_policy": "consolidated_as_of",
  "as_of": "2026-07-28T00:00:00Z"
}
```

### 3.2 Fields

| Field | Required | Semantics |
|---|---|---|
| `schema_version` | yes | Exact request-contract version. |
| `target.registrant_cik` | preferred | Ten-digit CIK of the target registrant. **Not** assumed equal to the accession prefix. |
| `target.ticker` | conditional | Discovery hint. MUST resolve to the same target CIK as every other hint supplied. |
| `target.name` | conditional | Discovery hint only. Fuzzy or multiple matches return `ambiguous` — never a guess, and never a model's choice. |
| `selector.kind` | yes | `exact` \| `sec_url` \| `period`. Fields belonging to another kind MUST be `null`. |
| `selector.accession_number` | for `exact` | Dashed accession. |
| `selector.sec_url` | for `sec_url` | An SEC filing-detail or component URL that normalises to exactly one accession. |
| `selector.form_type` | yes | Matched **exactly**. `10-K/A` is an amendment relationship, not an equivalent. `10-KT`, `NT 10-K`, `20-F` are rejected in v1.1. |
| `selector.report_period_end` | preferred for `period` | ISO date of the period covered. |
| `selector.fiscal_year` | optional for `period` | Year of `report_period_end`. Multiple matches return candidates. |
| `revision_policy` | yes | `exact_accession` \| `original` \| `consolidated_as_of`. |
| `as_of` | yes | Immutable reproducibility cutoff. |

### 3.3 `as_of` and revision policy

`as_of` is what makes a lookup reproducible. **Task 1 MUST NOT select a filing or amendment accepted
after `as_of`.** Without it, "the FY2025 10-K" silently changes meaning the day a `10-K/A` is
accepted.

| Policy | Meaning |
|---|---|
| `exact_accession` | Exactly the accession given. Amendments are recorded as relationships only. |
| `original` | The original `10-K`, ignoring later amendments except as relationships. |
| `consolidated_as_of` | The original `10-K` plus relationships to every amendment accepted on or before `as_of`. Each amendment keeps its own accession and, if acquired, its own bundle. |

**An amendment is an overlay, never an assumed replacement.** Task 1 never merges a `10-K/A` into the
original.

### 3.4 Conflicts are refused, not resolved

If ticker, name, target CIK, submitter CIK, form type, report period, URL, or accession disagree with
one another, Task 1 returns `selector_conflict`. It does not pick whichever is easiest to satisfy.

---

## 4. Bundle

### 4.1 Envelope

```json
{
  "schema_version": "acquisition-bundle/1.1",
  "profile_version": "sec-10k/1.1",
  "bundle_id": "bnd_...",
  "bundle_status": "verified",
  "created_at": "2026-07-28T00:00:00Z",
  "request": { },
  "resolution": { },
  "issuer": { },
  "filing": { },
  "documents": [ ],
  "relationships": [ ],
  "verification": { },
  "errors": [ ]
}
```

`request` is the request as received, echoed verbatim.

### 4.2 `resolution`

```json
{
  "status": "exact",
  "method": "cik_and_report_period",
  "candidate_count": 1,
  "candidates": [],
  "warnings": []
}
```

`status` ∈ `exact` | `ambiguous` | `not_found` | `failed_identity_check`.
**Only `exact` can produce `bundle_status: "verified"`.** When `ambiguous`, `candidates[]` carries
every viable `{target_registrant_cik, accession_number, form_type, report_period_end, filing_date}`
and the bundle is not verified.

### 4.3 `issuer`

```json
{
  "target_registrant_cik": "0000320193",
  "submitter_cik_from_accession": "0000320193",
  "archive_cik": "320193",
  "name": "Apple Inc.",
  "tickers": ["AAPL"],
  "registrants": [
    { "cik": "0000320193", "name": "Apple Inc.", "role": "target" }
  ],
  "identity_sources": [
    "https://www.sec.gov/files/company_tickers.json",
    "https://data.sec.gov/submissions/CIK0000320193.json"
  ]
}
```

### 4.4 `filing`

```json
{
  "accession_number": "0000320193-25-000079",
  "accession_number_compact": "000032019325000079",
  "form_type": "10-K",
  "report_period_end": "2025-09-27",
  "filing_date": "2025-10-31",
  "accepted_at": "2025-10-31T06:01:26-04:00",
  "revision_policy": "consolidated_as_of",
  "as_of": "2026-07-28T00:00:00Z",
  "primary_document_filename": "aapl-20250927.htm",
  "archive_base_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/",
  "filing_index_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm",
  "directory_index_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/index.json",
  "complete_submission_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079.txt"
}
```

### 4.5 `documents[]`

Every row of the filing index becomes a document record, whether or not its bytes were fetched. The
resolution snapshots are document records too.

```json
{
  "document_id": "doc_...",
  "role": "primary_10k",
  "sequence": "1",
  "document_type": "10-K",
  "description": "10-K",
  "filename": "aapl-20250927.htm",
  "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm",
  "declared_byte_length": 1520208,
  "acquisition_status": "verified",
  "representations": [ ],
  "warnings": []
}
```

**`role`** ∈ `primary_10k` | `complete_submission` | `submissions_metadata` | `filing_index` |
`directory_index` | `exhibit` | `xbrl_data` | `graphic` | `other`.

**`acquisition_status`** ∈

| Value | Meaning |
|---|---|
| `verified` | Bytes stored, hash recomputed, checks passed |
| `inventory_only` | Listed in the index; bytes deliberately not fetched |
| `not_retrieved` | Fetch was attempted or required and did not produce stored bytes; `not_retrieved_reason` explains |

`inventory_only` and `not_retrieved` carry **no `sha256` and no bytes**. A missing mandatory role
(§5.1) makes the whole bundle `partial` or `failed` — never `verified`.

### 4.6 `representations[]`

A document may have more than one representation. Each has its own identity and hash.

```json
{
  "representation_id": "rep_...",
  "representation_type": "raw_bytes",
  "media_type": "text/html",
  "charset": "utf-8",
  "byte_length": 1520208,
  "sha256": "hex",
  "retrieved_at": "2026-07-28T00:00:00Z",
  "storage_ref": "/api/v1/artifacts/doc_.../representations/rep_.../content",
  "derived_from_representation_id": null,
  "transform": null
}
```

A derived representation names its parent and the transform:

```json
{
  "representation_type": "normalized_text",
  "derived_from_representation_id": "rep_raw",
  "transform": { "name": "generic-html-to-text", "version": "1.0", "parameters_hash": "hex" }
}
```

Rules:

- **Raw bytes are stored exactly as served** — no normalisation, re-encoding, whitespace cleanup, or
  HTML-to-text conversion.
- **A derived representation MUST NOT overwrite its parent.**
- **The URL is provenance, not identity.** If the same URL later serves different bytes, that is a
  **new representation with a new `sha256`**; the earlier one remains valid and addressable.
- Task 1 v1.1 produces no derived representations of its own. The rule exists so that adding one
  later cannot destroy the original.

### 4.7 `relationships[]`

From **SEC metadata only**.

```json
{
  "relationship_type": "amended_by",
  "target_accession_number": "0000320193-26-000012",
  "target_bundle_id": null,
  "target_status": "not_yet_resolved",
  "as_of": "2026-07-28T00:00:00Z",
  "warnings": []
}
```

`relationship_type` ∈ `amends` | `amended_by` | `related_filing`.
`target_status` ∈ `resolved` | `not_yet_resolved` | `not_yet_filed` | `ambiguous` | `not_applicable`.

**`incorporates_by_reference` is deliberately absent.** Detecting that Part III is incorporated from
a proxy statement requires reading incorporation language inside the filing — document structure,
which is Task 2's side of the seam (§1). What Task 1 guarantees instead is that the inventory and
relationships are complete enough for Task 2 to represent an Item as *incorporated by reference*
rather than *missing*, **without fabricating text**. Items 10–14 being absent from the primary
document is a normal, correct outcome.

### 4.8 `verification`

```json
{
  "checks_passed": ["identity_single_target", "accession_format", "form_type_exact", "..."],
  "checks_failed": [],
  "hashes_recomputed": true
}
```

See §6 for the check list.

---

## 5. What gets retrieved

### 5.1 Mandatory — bytes plus integrity

A bundle cannot be `verified` unless all five are `acquisition_status: "verified"`:

1. **`primary_10k`** — the main 10-K document of the submission.
2. **`complete_submission`** — the full submission text file. It is the authoritative fallback when
   the primary document is malformed or the inventory is unusual.
3. **`submissions_metadata`** — the SEC submissions JSON used to resolve the filing.
4. **`filing_index`** — the filing detail/index page used.
5. **`directory_index`** — the archive directory `index.json`.

Items 3–5 are the **resolution evidence**. Without them, *"why this accession?"* cannot be answered
after the fact, which makes the resolution itself unverifiable.

### 5.2 Inventory only

Every other item the filing index lists — exhibits, XBRL instance and taxonomy files, images,
graphics — appears in `documents[]` with `filename`, type, `media_type` and `declared_byte_length`,
marked `inventory_only`. **No bytes are fetched and no hash is computed.** The inventory is complete:
every row of the filing index is present.

If Task 2 later needs an exhibit's bytes, that is a new requirement for Task 1 — not something Task 2
should work around by fetching from SEC on its own.

### 5.3 Never

Anything not part of the identified submission.

### 5.4 Caps, and the prohibition on silent truncation

Task 1 enforces a configurable size cap. **If a representation exceeds the cap it is NOT stored and
NOT hashed**, and is recorded as:

- `acquisition_status: "not_retrieved"`
- `not_retrieved_reason` — `exceeds_size_cap` | `fetch_failed` | `unavailable_at_source`
- `cap_bytes` — the cap in force
- `reported_size_bytes` — the source-reported size, when known

**Partial content is never stored under a verified status.** A downstream extractor that silently
receives half a document produces plausible, wrong output, which is the exact failure mode this
design targets.

### 5.5 Metadata visibility is not availability

A filing can appear in SEC metadata before every archive object is retrievable. Task 1 may retry
within a bounded budget, but **a bundle MUST NOT become verified on the strength of metadata alone**
when a mandatory representation is missing. It terminates `partial` or `failed` with
`pending_source_publication`.

---

## 6. Verification checks

Task 1 cannot emit `bundle_status: "verified"` until all of these pass:

1. Every issuer hint resolves to exactly **one** target registrant with a ten-digit CIK.
2. Target registrant, submitting CIK, archive CIK and any co-registrants are preserved separately and
   reconciled against SEC metadata.
3. Accession format is valid and matches the selected submissions record.
4. `form_type` matches exactly; a `10-K/A` is treated as a relationship, not a substitute.
5. `report_period_end`, `filing_date`, `as_of` and `revision_policy` are mutually consistent, and no
   date was inferred from another.
6. Archive CIK and compact accession in the path match the filing identity.
7. Filing index and directory index describe the **same** accession, form, period, inventory and
   primary document.
8. Primary-document URL, declared type, served media type and stored byte length are consistent.
9. The complete-submission header contains the expected accession and submission type.
10. Every stored representation's `sha256` and `byte_length` are **recomputed** from the stored bytes,
    not copied from a response header.
11. All five mandatory roles are `verified` and retrievable through `storage_ref`.
12. The emitted bundle validates against this schema version.
13. No model-generated value overrides SEC metadata or any deterministic check. Task 1's acquisition
    path is deterministic; a model may be used to interpret a user's natural-language request into a
    request object, and nowhere else.

Any conflict is preserved as a typed entry in `errors[]` and prevents `verified` when it affects a
mandatory invariant.

---

## 7. Statuses and error codes

### 7.1 `bundle_status`

| Value | Meaning |
|---|---|
| `verified` | Resolution `exact` and every mandatory artifact verified. **The only status Task 2 processes normally.** |
| `partial` | Identity exact, but a mandatory artifact or check is missing |
| `blocked` | Policy or source prevented acquisition |
| `failed` | Identity, integrity, or schema validation failed |

`ambiguous` and `not_found` are `resolution.status` values (§4.2), not bundle statuses; such a bundle
is `failed` with the corresponding error code, and carries `candidates[]`.

### 7.2 Error codes

| Code | Meaning | Bundle outcome |
|---|---|---|
| `needs_registrant_cik` | Accession does not resolve to one registrant | `failed` + candidates |
| `multiple_registrants` | More than one registrant disclosed and none designated target | `failed` + candidates |
| `ambiguous_identity` | Name or ticker matched several registrants | `failed` + candidates |
| `selector_conflict` | Supplied fields disagree (§3.4) | `failed` |
| `multiple_period_matches` | Period selector matched several filings | `failed` + candidates |
| `filing_not_found_as_of` | No matching filing accepted on or before `as_of` | `failed` |
| `pending_source_publication` | Metadata present, archive object not yet available after bounded retry | `partial` |
| `identity_mismatch` | Cross-source identity reconciliation failed | `failed` |
| `hash_mismatch` | Recomputed hash disagrees with what was stored | `failed` |
| `exceeds_size_cap` | Representation over cap (§5.4) | `partial` if the role is mandatory |
| `fetch_failed` / `unavailable_at_source` | Retrieval failed | `partial` or `failed` |
| `blocked_by_policy` | Access policy (§8) forbids the request | `blocked` |

Throttling, timeouts, and budget exhaustion are **error codes**, never alternative success statuses.

---

## 8. Access policy Task 1 applies

Recorded here so Task 2 inherits the same posture and does not accidentally undo it.

- Retrieval uses SEC's explicitly permitted archive path (`/Archives/edgar/data`, `Allow`-ed in
  `sec.gov/robots.txt`) and SEC's documented JSON APIs on `data.sec.gov`. The `cgi-bin` browse
  interface is `Disallow`-ed and is not used.
- Every request declares a `User-Agent` containing a real contact address, plus
  `Accept-Encoding: gzip, deflate`. **This is a functional precondition, not politeness** — SEC
  returns `403` without it.
- Self-imposed rate limit: **≤ 1 request/second**, an order of magnitude under SEC's published cap of
  10 rps.
- **Targeted retrieval only.** No enumeration, no crawling, no bulk download.
- `data.sec.gov` does not serve CORS headers, so acquisition is server-side by necessity as well as
  by design.

Sources: `https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data`,
`https://www.sec.gov/robots.txt` (verified 2026-07-26).

---

## 9. Transport, storage, and retention

```text
POST /api/v1/filings/acquisitions        body: AcquisitionRequest  →  202 { "run_id": "..." }
GET  /api/v1/runs/{run_id}                →  { run_status, bundle_id, error_code, timestamps }
GET  /api/v1/filings/bundles/{bundle_id}  →  the bundle (§4)
GET  /api/v1/artifacts/{document_id}/representations/{representation_id}/content  →  exact bytes
```

The last URL is what `storage_ref` contains. There is deliberately **no extraction endpoint** on the
Task 1 side.

- Identifiers are opaque and are **not** authorisation secrets. v1.1 has no authentication; artifacts
  are the same publicly inspectable run evidence the Task 1 frontend shows.
- **Retention is governed by the Task 1 deployment policy** (an age bound and a total-size bound,
  oldest-first eviction). This contract deliberately does **not** define a second retention rule.
- **Expiry is a recorded state, not a 404.** An expired representation keeps its metadata — id,
  source URL, `retrieved_at`, `sha256`, `byte_length`, and the expiry date — and reports itself as
  expired. Structure stays auditable after the bytes are gone.
- If Task 2 needs bytes beyond retention, it copies them into its own content-addressed store, or
  requests reacquisition. **Reacquisition produces a new bundle and new representation IDs**; a
  deleted artifact is never silently reconstructed under its old identity.

---

## 10. What Task 2 must not assume

- **Not that a retrieval succeeded.** Always read `bundle_status` and each `acquisition_status`.
- **Not that the accession prefix is the company** (§2.2).
- **Not that a `10-K/A` replaces the original filing** (§3.3).
- **Not that every Item appears in the primary document.** Items 10–14 are legitimately incorporated
  by reference; Item 6 is reserved; Item 16 is optional; sub-items such as 1A–1C and 9A–9C exist. The
  form is not a contiguous 1-through-16 list. An extractor that treats "Item 10 not found" as a
  failure will report failures on correct filings; an extractor that fills it in from elsewhere will
  report a confident wrong answer, which is worse.
- **Not that bytes are text**, or that the primary document is HTML. `media_type` is what the source
  served; encoding detection is Task 2's problem.
- **Not that `inventory_only` means content is available.**
- **Not that content has been cleaned.** Nothing has been normalised.
- **Not that ticker mappings are authoritative.** The verified CIK is.
- **Not that XBRL facts represent narrative Item boundaries.**
- **Not that re-fetching from SEC is free.** Acquiring is now yours (v1.2), but it happens **once**,
  in the acquisition stage, under SEC's fair-access limits. The extractor reads `storage_ref`. A
  parser that re-fetches mid-run produces a result nobody can reproduce.
- **Not that a citation or a model's judgement alone proves an extracted span.**

---

## 11. Conformance test

The seam is validated by a program written **against this document only**. That program:

1. Submits a request by `(target_registrant_cik, accession_number)`, and separately by ticker plus
   fiscal year.
2. Obtains the bundle through the public interface.
3. Confirms all five mandatory roles are `verified`, each with `byte_length`, `media_type`, `sha256`,
   `retrieved_at` and a working `storage_ref`, and that **recomputing SHA-256 over the fetched bytes
   matches**.
4. Confirms the inventory lists every filing-index row, each `inventory_only` carrying no hash.
5. Forces the cap and confirms the oversized representation is `not_retrieved` with a reason, no
   bytes, no hash — and that the bundle is not `verified`.
6. Resolves a filing whose **submitting CIK differs from the target registrant**, and confirms the
   three CIK forms are recorded separately (§2.2).
7. Runs a period lookup with an `as_of` **earlier than a known `10-K/A`'s acceptance**, and confirms
   the original filing is returned with the amendment recorded as a relationship, not substituted.
8. Submits an ambiguous company name and confirms a **candidate set** comes back, not a choice.

It MUST NOT import Task 1 internal modules. If it needs to, this document is incomplete — fix the
document. **This rule binds the conformance test, not a Task 2 product**: a Task 2 build may reuse
Task 1's store, run model and frontend.

---

## 12. Out of scope for this contract

No item schema. No content parsing. No cross-filing normalisation. No historical backfill. No exhibit
byte retrieval. These are Task 2 decisions and are not pre-empted here.

---

## 13. Changelog

### v1.2 (2026-07-29) — the producer does not exist, so the document changes role

Task 1 shipped without an acquisition layer. This version does not change a single field, status or
check: it changes who is obliged to satisfy them, from "the other half of the system" to "the
acquisition stage you are about to write". The prohibition on fetching from SEC (§10) is void and
inverted; everything else stands. §14 is new and records what Task 1 actually produced that is worth
carrying over. Recorded here rather than by quietly editing v1.1, because a contract that changes
its meaning without saying so is the failure this whole submission argues against.

### v1.1 (2026-07-28)

Adopted from the product owner's earlier `Q1_Q2_SEC_FILING_CONTRACT.md` proposal — since removed from
the repository, because two documents that both look binding is a trap. **This file is the only
contract.** The decision record is Amendment 16 of the Task 1 spec. Every change fixes a case where v1.0 would have produced a **confident wrong
answer**, not a missing convenience:

- **§2.2** three CIK forms preserved separately; the target registrant is the identity; an accession
  that does not resolve to one registrant returns `needs_registrant_cik`. v1.0's "`cik` — the CIK of
  the filer" was wrong for agent-submitted and multi-registrant filings.
- **§2.3** four separate dates, none inferred from another.
- **§3** a concrete request schema with tagged-union selectors, plus `as_of` and `revision_policy`;
  amendments are overlays, never replacements; conflicting hints are refused rather than resolved.
- **§4** a concrete bundle schema: resolution, issuer, filing, documents, representations,
  relationships, verification, errors.
- **§4.6** raw vs derived representations; raw is immutable; changed bytes at a stable URL produce a
  new representation.
- **§4.7** amendment relationships from SEC metadata only; `incorporates_by_reference` explicitly
  left to Task 2.
- **§5.1** the resolution snapshots are mandatory, stored and hashed.
- **§5.5** metadata visibility never equals availability.
- **§6** an explicit thirteen-check gate for `verified`.
- **§7** explicit status and error-code tables.
- **§9** transport endpoints and the expiry-is-a-recorded-state rule.
- **§11** three added conformance cases; the internal-module rule clarified as binding the test, not
  a Task 2 product.

**Deliberately not adopted**, so their absence is a decision rather than an oversight:

- a **2 rps** rate limit — our ≤ 1 rps stands; loosening a published self-imposed limit for
  convenience is the wrong direction;
- **capability-token authorisation, signed content URLs, and a separate 7-day retention rule** — no
  auth system exists, artifacts are already public run evidence, and retention is governed by the
  deployment policy; a second conflicting retention rule in this contract would be a trap;
- an **extended acquisition profile** that eagerly fetches every textual document and resolves
  related filings — close to SEC's prohibition on enumeration, and it buys a first Task 2 build
  nothing. The mandatory five plus a complete inventory stand;
- a **Task 1-emitted evidence/locator object** — text offsets and DOM paths into a 10-K are Task 2's
  coordinate system. Task 1 guarantees stable `document_id`, `representation_id` and `sha256`; Task 2
  builds locators on those and must not alter them.

Future coverage, not required for v1.1: legacy text and malformed-HTML filings, PDF-primary filings,
the large-complete-submission budget boundary, and the authorisation cases that arrive with an auth
system.

---

## 14. What Task 1 actually built, and what you now have to build

Written at the point where Task 1 was submitted, so that Task 2 starts from what is true rather than
from what this document assumed on 2026-07-28.

### 14.1 Reusable, and worth reusing

None of this is 10-K-specific, and all of it exists as working code in this repository.

| What | Where | Why it transfers |
|---|---|---|
| **Evidence-first verification** — a claim counts only if deterministic code re-locates the value inside the *stored* bytes, not the live source | `app/verifier.py` | The whole argument of Task 2 is "the extractor said Item 7 starts here." That is a proposal. Re-finding the boundary in the stored filing is the check. Same shape, different corpus |
| **A frozen, hashed postcondition** compiled before any work starts | `app/postcondition.py` | Deciding what counts as a correct extraction *after* seeing the document is how a parser talks itself into an answer |
| **A closed status taxonomy**, extended only by written amendment, where partial results are never rendered as success | `app/models.py` | Item statuses have exactly this problem: `present` / `reserved` / `optional_absent` / `incorporated_by_reference` is a closed set or it is nothing |
| **Content-addressed artifact store** with dated expiry rather than dangling references | `app/store.py`, `app/evidence.py` | §9's retention rule is already implemented here |
| **`robots.txt` (RFC 9309) enforcement, egress guard, rate limiting** | `app/robots.py`, `app/egress.py` | SEC publishes a fair-access policy and a rate limit. §8 assumed these were solved because they were |
| **A held-out evaluation discipline**: hashes committed before the split runs, scored once, published afterwards | `eval/holdout-manifest.md`, `eval/harness.py` | The single most useful thing Task 1 did. It is also what produced its worst number |
| **Fail-closed budgets** producing an explicit exhaustion status instead of a partial answer | `app/executor.py` | A 10-K is large; a cap you silently hit is a truncated Item nobody flagged |
| **Frontend patterns** — pre-executed runs so a cold container is never a blank page, an evidence drill-down, an executable limitations list | `app/templates/`, `app/limitations.py` | The submission requires an operable frontend that makes failures inspectable. This is a worked example of that requirement |

### 14.2 What you have to build that this document assumed you would be handed

1. **Resolution** — company name or ticker or CIK to one registrant and one accession, with a
   candidate set returned rather than a guess when it is ambiguous (§2, §3.4).
2. **Acquisition** — the mandatory five representations, fetched once, hashed, with the resolution
   snapshots stored (§5.1). Fetching is now yours; the discipline around it is not negotiable.
3. **The bundle itself** and the thirteen-check `verified` gate (§4, §6).
4. **The conformance test** in §11, which no longer tests somebody else's producer but your own.

### 14.3 Four things Task 1 got wrong that will happen to you

These cost real days. They are listed because the shape recurs, not because the details transfer.

1. **A check that reports on a coincidence.** Fifteen defects were found in Task 1's own checking
   machinery; ten were the same species — a check that passed for a reason unrelated to what it
   claimed to verify. The extraction analogue is a boundary test that passes because the heading
   happens to be unique in that filing.
2. **A published claim nobody executed.** Four of seven published limitations did not reproduce as
   written. Every claim about behaviour must be executable against the deployment, and re-executed
   before submission.
3. **A conclusion drawn from an aggregate instead of a case.** A failure-class histogram was read as
   a policy finding; opening one stored trace showed it was a network timeout. For Task 2 the
   temptation is stronger, because item-level accuracy aggregates beautifully and hides exactly the
   filings that matter.
4. **A promise stated more widely than it was implemented.** A record promised per
   `site × operation` was implemented for one hard-coded page. Whatever Task 2 promises per filing
   *class*, verify it holds for a filing in that class that appears in no evaluation case.

### 14.4 Numbers worth knowing before you plan

Task 1's held-out result was **1 of 8**, against **10 of 11** on its own development set. The gap was
not capability: five of the eight never began work — three to a transient network failure and two
because the task named no starting point. **A self-authored evaluation set measures how well a system
answers what it accepts, and cannot measure how much it accepts.** Whatever Task 2's held-out set is,
write it before the extractor exists, and have someone who has not read the extractor write it.

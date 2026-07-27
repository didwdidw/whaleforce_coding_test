# The paid key on the grading host — what protects spend once absence no longer does

**Status: both recommendations approved by the product owner (2026-07-27).** The separate
scored workload is **not built yet** — it goes into the spec first. The spend ceiling is
built now, for the reason in §4.

## The question

The spec's Common Requirements say held-out cases **are run against the deployed system**.
So M8 is online, not a locally started copy. If the paid credential ever lands on that host,
the protection currently doing the work — *the key is simply not there* — is gone, and what
stops a visitor's run from spending money is code. A10.7 already ruled on that shape: a
control whose misconfiguration resolves to permissive is a control that will eventually be
off.

## First, a distinction that removes most of the problem

Two different things are called "evaluation", and only one of them needs the paid key:

| | Who runs it | Where | Credential |
|---|---|---|---|
| **Our validation / test splits** | us | wherever we choose | paid, unconditionally (A9.6) |
| **The graders' held-out cases** | them | the public URL | whatever the public demo uses |

A9.6 is about the first row. Nothing in it requires the *public* service to hold a paid key.
That is the opening worth using.

## Recommendation 1 — keep the separation physical, not conditional

**The paid key never enters the public app container.** Scored rounds run as a separate
workload on the same host — a Kubernetes Job, or a second Zeabur service with no domain
attached — that mounts the paid key, sets `CREDENTIAL_POLICY=scored`, and shares the same
volume so its evidence lands in the same store.

The property this preserves is exact: **the process that serves anonymous traffic has no
paid credential on its filesystem**, at M8 as much as today. "The key is not there" stays
literally true for that process, so the protection is not replaced by a conditional — it is
still absence, just scoped to the container that matters.

What it costs: the scored round is launched through that workload rather than by typing into
the public URL. We were going to run those ourselves anyway.

### Conditions attached to the approval

1. **No public domain on that service.** Zeabur hands every service a free `*.zeabur.app`
   name, and accepting one would put the paid credential behind a URL whose only protection
   is that nobody has guessed it. The scored round is launched as a workload, not by
   requesting a page, so it does not need a URL at all — and not having one is a stronger
   statement than having an unadvertised one.
2. **Verify the shared volume rather than assuming it.** `RWO` normally permits two pods on
   the same node, but that is the easy half. The half to look at first is **two SQLite
   writers**: both processes open the same database, and both would run
   `enforce_retention()` on startup. Two concurrent sweeps evicting from the same table is a
   race that ends with one process's expiry decisions applied to rows the other has already
   changed. This needs a decision (WAL, an advisory lock, or retention owned by exactly one
   role) before the second workload exists, not after.
3. **RAM.** The box has ~1.7 GB spare and the app peaks at a measured 899.9 MiB. A second
   container is tight, so **a scored round must not run alongside heavy load** — that
   constraint belongs in the deploy runbook, not in someone's memory.

## What it does not solve

The graders' own traffic then runs on the **free tier**, and the free tier is one full round
per day (RPD 500 against ~294 requests per round, measured at M0). If they run a full round
on a day we have also been testing, they can hit `blocked / provider_quota` — an honest
failure, and a bad first impression.

Mitigations that cost nothing:

- **Fixture operations do not call a model at all.** Everything demonstrable on the fixture —
  every verified claim, both proofs of absence, the shortcut case, the partial — runs
  deterministically. Only genuinely open-ended tasks consume quota.
- **The pre-executed homepage runs are pinned and dated**, so the first screen is inspectable
  with zero provider calls.
- **Stop testing against production before submission.** Operational, not architectural.

## Recommendation 2 — the spend ceiling is load-bearing today

Not speculative work against a policy that might change. The paid credential is **already in
use** — the model comparison ran on it — and A8.10's USD 5 self-approval ceiling currently
exists only as a number a person is holding in their head. Nothing at runtime enforces it.
Nothing counts against it. A limit that is only remembered is not a limit; the engineering
work here is turning a number in someone's head into something the code can refuse.

The same mechanism happens to be what would replace the absence-protection if the public
path ever needed paid access, but that is a consequence, not the reason.

The ceiling:

- a **cumulative USD-per-day ceiling**, stored in the volume-backed database so it survives
  restarts, checked **before** each call, not after;
- exceeding it is `blocked / provider_quota` — refusal, never a silent continue, so the
  failure mode is the safe direction;
- the current figure visible on `/healthz` next to the credential state;
- underneath the existing per-session cap, which already bounds one visitor to ~10 runs
  ≈ $0.04 at measured rates.

Under the current policy the *public* path never reaches it, because the public path never
reaches a paid credential at all. Development and evaluation do, and that is where the USD 5
ceiling has been unenforced since the first paid call.

**Standing rule, unchanged until the owner changes it:** free → paid fallback is automatic
for development and evaluation, and forbidden on the public demo path, which stays
`blocked / provider_quota`.

## 5. The vulnerability this work exposed

Recorded here as evidence for the analysis report, not as an aside.

While writing the test that proves the store cannot reach the key directory, the first run
**deleted the key file**. The cause was not a boundary that was insufficiently strict. It
was **arbitrary file deletion and arbitrary file read**:

- `Store._expire()` unlinked whatever path an artifact row held. The path came from the
  database and was never checked against the store directory.
- `Store.read_artifact()` read and returned whatever path the row held, and that return
  value is served over HTTP by `/api/artifacts/{id}`.

Together: any influence over that column is file deletion and file disclosure on the host,
in a product whose central claim is a defensible security posture. It has been present since
M2, when the store was written.

The part that belongs in the report is not the bug. It is that **107 passing tests did not
find it**, and the test that did was written because someone asked for proof rather than
assurance. Everything before it tested the store doing its job correctly; nothing tested it
being pointed somewhere it did not belong. That gap has the same shape as the M1 lesson —
verifying structure and assuming content — one layer down.

Both paths now resolve the path and require it to be inside the artifact directory; a row
that points outside loses its bytes and keeps its file, and the refusal is logged.

## What is already true today

- Keys are read from files only, never from the environment — enforced by parsing the
  provider module for environment access, not by grepping it.
- The key directory sits **outside** the artifact store root, and that relationship is
  asserted in the suite rather than assumed.
- A public-demo provider lists no paid tier as usable **even when a paid key is present on
  disk**, which is the case that starts mattering the day the key arrives.
- `/healthz` reports presence and tier only — no value, no prefix, no length.

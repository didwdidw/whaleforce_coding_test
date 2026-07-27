# The paid key on the grading host — what protects spend once absence no longer does

**Status: a recommendation, not a decision.** It changes what money anonymous traffic can
reach, so it is the product owner's call. Written now because the answer changes what M8
looks like, and rebuilding it then is the expensive version.

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

## Recommendation 2 — build the ceiling now, whether or not it is ever needed

If the answer later becomes "the public path must survive free-tier exhaustion", the
absence-protection is gone by definition and something measured has to replace it. That
something should exist and be exercised **before** the day it matters:

- a **cumulative USD-per-day ceiling**, stored in the volume-backed database so it survives
  restarts, checked **before** each call, not after;
- exceeding it is `blocked / provider_quota` — refusal, never a silent continue, so the
  failure mode is the safe direction;
- the current figure visible on `/healthz` next to the credential state;
- underneath the existing per-session cap, which already bounds one visitor to ~10 runs
  ≈ $0.04 at measured rates.

Written under the current policy — free-only on the public path — the ceiling never fires.
That is the point: it is a control that has been in place and observed doing nothing, rather
than one written under time pressure on grading day.

**Standing rule, unchanged until the owner changes it:** free → paid fallback is automatic
for development and evaluation, and forbidden on the public demo path, which stays
`blocked / provider_quota`.

## What is already true today

- Keys are read from files only, never from the environment — enforced by parsing the
  provider module for environment access, not by grepping it.
- The key directory sits **outside** the artifact store root, and that relationship is
  asserted in the suite rather than assumed.
- A public-demo provider lists no paid tier as usable **even when a paid key is present on
  disk**, which is the case that starts mattering the day the key arrives.
- `/healthz` reports presence and tier only — no value, no prefix, no length.

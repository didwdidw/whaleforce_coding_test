# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Prompt logging (mandatory, every session)

This repo is a submission for a coding test whose graders will read the prompt records. Logging is
part of the deliverable, not housekeeping.

- Every session has its own file under `prompts/`, named after the session (e.g. `prompts/PM-Session.md`).
  At the start of a session, either continue the file for that session or create a new one, and state
  the session name / role / scope at the top.
- **Log every user prompt verbatim**, in order, as it arrives — including the one asking for the log
  itself. Do not paraphrase, summarise, or clean up wording.
- Separate prompts with a line containing only `==========`.
- Append the log in the same turn the prompt is handled, so nothing gets reconstructed after the fact.

## Repository state

Greenfield — no application code, build system, or test runner yet. Replace this section with real
build / test / run commands once a stack is chosen.

`task_description/` holds the test spec (EN + ZH, same content; EN is canonical). It is gitignored on
purpose: the repo is public and the problem statement must not be published.

## Scope

Only **Task 1 — Generalized Browser Automation Agent** is in scope right now. Do not start work on
Task 2 (SEC 10-K extraction) unless explicitly asked.

## Constraints that shape the repo

Graded directly, from the spec's Common Requirements:

- Commit history must reflect real incremental development — do not squash the process away.
- Each submitted task needs a publicly accessible **web frontend**, not just an API: it must accept
  tasks, show execution progress/results, and make failures inspectable.
- A self-built **evaluation set** per task, plus an honest list of what works and what is unreliable.
  Held-out cases will be run against the deployed system.
- README: how to run, key design decisions, where AI helped.
- Analysis report: runtime performance, cost, scalability, and how correctness is verified.
- Public or self-created data only.

For Task 1 specifically, self-correction and self-maintenance must be substantive mechanisms —
try/except retry loops are explicitly called out as insufficient — and silent failures (plausible but
wrong results) are penalised more heavily than loud ones.

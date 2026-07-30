# Prompt records — where the decisions are

Three logs, all verbatim and in order, because that rule is what makes them evidence rather than a
highlight reel: **every** prompt is here, including the dull ones and the ones that turned out to be
wrong. Nothing was edited after the fact.

That also makes them long. This index is the reader's entry point (A14.15): what each file is, and
where the substantive decisions happen.

| File | Session | What it is |
|---|---|---|
| `PM-Session.md` | Product owner / acceptance | Scoping, the spec, the acceptance criteria, and every ruling. Never wrote product code |
| `Engineering-Session.md` | Engineering | Implementation from the frozen spec. Never decided what "correct" meant |
| `Final-Reviewer-Session.md` | Independent review | Four rounds against the deployed site, read-only, without reading any product code. Never fixed anything it found. Its output is `acceptance-report.md` |

The separation is the point, and it is the same idea as the product's own design: a session that both
defines success and reports success will report success, exactly as an agent that both answers and
verifies will verify itself. The third session exists because the first two share a premise — both
had read the spec — and the defect that mattered most was one only a reader without that premise
could see (Amendment 28). `docs/task1-spec.md` §16 is the durable output — twenty-eight numbered
amendments appended to frozen text, each naming the defect that caused it.

## The decisions worth reading

Roughly in the order they were taken. Each one is findable by searching the file for the quoted
phrase or the amendment number.

| Where | What was decided, and why it mattered |
|---|---|
| `PM-Session.md`, scoping | **Two real sites, not five.** Breadth is answered by an experimental tier measured with an interval, not by counting declared sites — and the frontend must present that as a chosen trade-off rather than as unfinished work |
| `PM-Session.md`, arXiv | **arXiv dropped**, because its robots policy disallows the operations we wanted. Recorded as a policy refusal rather than repackaged as a research decision |
| `PM-Session.md`, Amendment 1 | **The fixture is withdrawn from the promised set.** A reliability figure measured on a site we wrote is us setting our own exam; the fixture operations become mechanism evidence and appear in no success rate |
| `PM-Session.md`, Amendment 3 | **Absence is never inferred.** `no_result_verified` requires a located empty-state element or a coverage anchor. This costs measured points and is kept |
| `Engineering-Session.md`, M1 report | **The two defects that shipped.** A mis-route that answered a different question perfectly, and a greedy regex that searched for a sentence and reported "0 results". Both looked like clean runs. The verifier layer exists because of these |
| `Engineering-Session.md`, Amendment 17 | **The plan was never compared against the task.** A request to sort by *CIK ascending* got the canned *GICS Sector descending* plan, executed it perfectly and returned `succeeded_verified`. Four dev cases were being answered that way |
| `PM-Session.md`, Amendment 20 | **A push is a deployment** on this host, so neither session pushes during a scored round or an idle window |
| `PM-Session.md`, Amendment 23 | **The spend ceiling measures billed dollars only.** Free-tier calls are priced for reporting and never enforced against — the sum had the public container, which holds no billing credential, on course to refuse work after spending nothing |
| `Engineering-Session.md`, Amendment 24 | **The scorer was wrong, and it was not fixed on the spot.** Four correct runs were being demoted by the harness reading rendered text only. The engineering session diagnosed it, reproduced it against the stored artifacts, and left it alone — changing it makes a gate pass, which is the product owner's call |
| `PM-Session.md`, Amendment 24 | The ruling on the above: fix it, **fence it with a regression case**, and re-run twice — once with the scorer fix as the only change, once after the product fixes — so the two effects stay attributable |
| `PM-Session.md`, Amendment 25 | **The subtraction.** After an independent review ran the deployed system: Task 2 cut, the mutation sweep cut, the validation split cut, and the README and analysis report moved from last to first because every previous plan had put them last and they had slipped every time |

## What the logs show about working this way

Three things a reader can check rather than take:

1. **The amendments are numbered and appended, never edited.** A defect found later does not get to
   rewrite the text that permitted it.
2. **The engineering session stops and asks** where a decision would change what is promised, what
   counts as verified, or what money is spent — and the log shows it stopping.
3. **The corrections that matter came from running the deployed system**, not from reading diffs. The
   three most damaging defects in this repository — a published limitation whose remedy did not work,
   a promised record frozen to one product, and a live silent failure on a two-part question — were
   all found that way, all after the code had been reviewed.

# Held-out Eval Manifest

The validation and test splits were **deliberately not in this repository** for the whole of
development: their content was delivered to the product owner out-of-band, and only counts and
hashes were committed, so the splits were auditable without being readable. **Both are now
published**, at submission, as A14.5 always said they would be — the test split has been scored once
and its number is fixed, so withholding it now would protect nothing and would leave the hashes
above pointing at files no reader can check.

**Verify them.** The hashes in the table were committed *before* either split was run; the files
beside them are the ones that were scored:

```bash
shasum -a 256 eval/validation-set.md eval/test-set.md   # must match the table below
```

`test-deploy-e82cacb9e809-r4.json` records `eval_set_file: test-set.md` and the same hash in its
provenance, so the score, the file and the pre-committed hash form a closed loop that does not
depend on trusting us.

Policy: `docs/task1-spec.md` §10.1 and Amendment 6.

| Split | Cases | SHA-256 of case content | In repo |
|---|---|---|---|
| dev | 15 | see `eval/dev-set.md` (committed) | yes |
| validation | 8 | `0ebb86c047cff19d716add85e8102e3edbe5c041390fd8b1b5e2c8531e36861c` | **yes**, `eval/validation-set.md` — published unrun |
| test | 8 | `43ee8ce52acf6470309148c3ca282be63977622a934776f97f40908d2b54e34e` | **yes**, `eval/test-set.md` — published after being scored once at `r4` |

Hashes are over the delivered Markdown, byte for byte.

## Rules

- The engineering session MUST NOT be shown validation or test case content — **in force for the
  whole of development, and discharged at submission.** The engineering session first read the test
  split *after* `r4` was scored, to resolve run-to-case ids while rescuing that round's evidence;
  the score was already taken and immutable by then. The validation split was never read by anyone
  during development and was never executed.
- Validation is executed by the harness on the product owner's behalf during the engineering session.
  The engineering session receives only the aggregate score and the `failure_class` histogram
  (S-10.4).
- Test is executed **once** against the deployed system by the acceptance session. That first run is
  the reported score (S-10.6) — it happened at `r4`, on build `e82cacb9e809`, and it is **1 of 8**.
  **That run has now happened, so this split is a regression suite from here on and must be
  described as one — never again as held-out.** Any number produced from it in future is a
  regression check against a set that has been read, and carries none of the authority of the first
  run.
- **Validation was never run**, deliberately (Amendment 25): its purpose was to keep the engineering
  session honest *during* development, and development ended. It is published here so that the
  claim "we really did hold it back" has a file behind it rather than only a sentence. Running it
  now would buy a number in exchange for the only thing it was ever for.
- Every first run records git SHA, pinned model ID, and the eval-set hash above (S-10.7).

## Split composition

Both held-out splits are 4 promised-record cases (one per record: OP-4, OP-5, OP-6, OP-7) plus 4
behavioural cases (XB-1 proof of absence, XB-4 shortcut refusal, XB-5 refusal and experimental
abstention).

Held-out cases differ from dev cases by entity, page type, operation order, or expected result type —
not by wording (A6.4). Each held-out case records which of those dimensions it varies.

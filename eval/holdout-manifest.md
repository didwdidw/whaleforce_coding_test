# Held-out Eval Manifest

The validation and test splits are **deliberately not in this repository**. Their case content was
delivered to the product owner out-of-band and is stored outside the repo. This file exists so the
splits are auditable — counts and content hashes are committed, content is not.

Policy: `docs/task1-spec.md` §10.1 and Amendment 6.

| Split | Cases | SHA-256 of case content | In repo |
|---|---|---|---|
| dev | 15 | see `eval/dev-set.md` (committed) | yes |
| validation | 8 | `0ebb86c047cff19d716add85e8102e3edbe5c041390fd8b1b5e2c8531e36861c` | **no** |
| test | 8 | `43ee8ce52acf6470309148c3ca282be63977622a934776f97f40908d2b54e34e` | **no** |

Hashes are over the delivered Markdown, byte for byte.

## Rules

- The engineering session MUST NOT be shown validation or test case content.
- Validation is executed by the harness on the product owner's behalf during the engineering session.
  The engineering session receives only the aggregate score and the `failure_class` histogram
  (S-10.4).
- Test is executed **once** against the deployed system by the acceptance session. That first run is
  the reported score (S-10.6). After it has been inspected, the split is a regression suite and must
  be described as one — never as held-out.
- Every first run records git SHA, pinned model ID, and the eval-set hash above (S-10.7).

## Split composition

Both held-out splits are 4 promised-record cases (one per record: OP-4, OP-5, OP-6, OP-7) plus 4
behavioural cases (XB-1 proof of absence, XB-4 shortcut refusal, XB-5 refusal and experimental
abstention).

Held-out cases differ from dev cases by entity, page type, operation order, or expected result type —
not by wording (A6.4). Each held-out case records which of those dimensions it varies.

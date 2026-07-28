"""Carrying a scored round's evidence out with the round (A22.7, A22.8).

The workload that runs scored splits has a volume nothing else can read (A21.1), so the
runs whose numbers we publish would otherwise be the only runs nobody can look at — and the
failures, which are the ones a reader has most reason to doubt, would be the least reachable
of all. A21.2 already established how a paid round's record leaves that volume: it travels
in the repository. This extends the same mechanism to the evidence.

What is carried, in priority order:

  1. **every non-success run**, complete. There are fewer of them than of the successes, and
     they are the ones the assignment means by *inspectable failures*;
  2. **a sample of successes named before the round** (`eval/bundle-sample.json`), so a
     reader can check that a pass looks like a pass rather than taking the label;
  3. for everything left out — the per-case verification record, the artifact hashes, and an
     explicit list of what was omitted and why (A11.8). Absence is recorded, not inferred.

The cap is applied against **measured** sizes: every candidate is weighed first, and what
does not fit is named. That residue is the real limitation, written against what could not
be carried rather than against the whole category.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
from typing import Any

BUNDLES_VERSION = "bundles/1.0"
REPO = pathlib.Path(__file__).parent.parent
SAMPLE_FILE = REPO / "eval" / "bundle-sample.json"
#: What one round may add to the repository. A policy number, not a measurement — what is
#: measured is each bundle, so the decision about what exceeds it is never a guess.
CAP_MIB = float(os.environ.get("EVAL_BUNDLE_CAP_MIB", "48"))


def named_sample(split: str) -> list[str]:
    """The successes to carry, read from a file that predates the round.

    Choosing after the round is choosing which pass to show. If the declaration is missing
    the answer is an empty sample and a stated reason — not a sample invented here.
    """
    try:
        declared = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list((declared.get("splits") or {}).get(split) or [])


def classify(cases: list[dict[str, Any]], sample: list[str]) -> dict[str, list[dict]]:
    """Which bundles are required, which are wanted, and which are neither."""
    required, wanted, rest = [], [], []
    for case in cases:
        if not case.get("counts_as_success"):
            required.append(case)
        elif case.get("case") in sample:
            wanted.append(case)
        else:
            rest.append(case)
    return {"required": required, "wanted": wanted, "rest": rest}


def weigh(store: Any, run_id: str) -> tuple[int, list[dict[str, Any]]]:
    """Total stored bytes for a run, and the artifact refs behind that number."""
    refs = [ref.to_dict() for ref in store.artifacts_for_run(run_id)]
    return sum(int(ref.get("length") or 0) for ref in refs), refs


def export(report: dict[str, Any], split: str, store: Any, out_dir: pathlib.Path,
           *, cap_mib: float = CAP_MIB) -> dict[str, Any]:
    """Copy what fits, hash what does not, and say which is which.

    Returns the manifest. It is written next to the bundles so the two travel together: a
    manifest that lives somewhere else is a manifest that gets separated from the thing it
    qualifies.
    """
    cases = report.get("cases") or []
    sample = named_sample(split)
    groups = classify(cases, sample)
    cap_bytes = int(cap_mib * 1024 * 1024)

    out_dir.mkdir(parents=True, exist_ok=True)
    carried: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    used = 0

    def record_omission(case: dict[str, Any], reason: str, refs: list[dict]) -> None:
        omitted.append({
            "case": case.get("case"),
            "run_id": case.get("run_id"),
            "terminal_status": case.get("terminal_status"),
            "counts_as_success": bool(case.get("counts_as_success")),
            "why_omitted": reason,
            # A11.8: what is missing is stated with enough to identify it later, so its
            # absence is a recorded fact rather than something a reader has to notice.
            "verification": case.get("evidence"),
            "artifacts": [{"artifact_id": ref.get("artifact_id"), "kind": ref.get("kind"),
                           "sha256": ref.get("sha256"), "length": ref.get("length"),
                           "source_url": ref.get("source_url")} for ref in refs],
        })

    for group, reason_if_dropped in (("required", "over the size cap"),
                                     ("wanted", "over the size cap"),
                                     ("rest", "not required by A22.7 and not in the "
                                              "pre-named success sample")):
        for case in groups[group]:
            run_id = case.get("run_id")
            if not run_id:
                record_omission(case, "the case produced no run to collect evidence from", [])
                continue
            size, refs = weigh(store, run_id)
            if group == "rest":
                record_omission(case, reason_if_dropped, refs)
                continue
            if used + size > cap_bytes:
                record_omission(case, reason_if_dropped, refs)
                continue
            written = _write_bundle(store, case, refs, out_dir)
            used += size
            carried.append({"case": case.get("case"), "run_id": run_id,
                            "counts_as_success": bool(case.get("counts_as_success")),
                            "reason": ("non-success run (A22.7)" if group == "required"
                                       else "pre-named success sample (A22.7)"),
                            "bytes": size, "files": written})

    sample_carried = [c["case"] for c in carried if c["case"] in sample]
    manifest = {
        "tool": BUNDLES_VERSION,
        "split": split,
        "git_sha": (report.get("provenance") or {}).get("git_sha"),
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cap_mib": cap_mib,
        "measured_bytes_carried": used,
        "measured_mib_carried": round(used / 1024 / 1024, 3),
        "cases_total": len(cases),
        "non_success_total": len(groups["required"]),
        "non_success_carried": sum(1 for c in carried if not c["counts_as_success"]),
        "sample_declared": sample,
        "sample_carried": sample_carried,
        "sample_short_by": [name for name in sample if name not in sample_carried],
        "carried": carried,
        "omitted": omitted,
        "note": ("Sizes are measured, not estimated: every candidate bundle is weighed "
                 "from the store before the cap is applied. Anything under `omitted` with "
                 "`over the size cap` is the residue A21.4 is written against — it names "
                 "what could not be carried rather than the whole category."),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def _write_bundle(store: Any, case: dict[str, Any], refs: list[dict[str, Any]],
                  out_dir: pathlib.Path) -> list[str]:
    """One directory per case: the artifacts, and the record they are evidence for."""
    case_dir = out_dir / str(case.get("case") or case.get("run_id"))
    case_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for ref in refs:
        blob = store.read_artifact(ref["artifact_id"])
        if blob is None:
            continue
        name = f"{ref['artifact_id']}.bin"
        (case_dir / name).write_bytes(blob)
        # Re-hashed on the way out. A hash copied from the row that describes the file
        # proves the row and the file agreed once, not that this copy is that file.
        ref["sha256_on_export"] = hashlib.sha256(blob).hexdigest()
        ref["sha256_matches"] = ref["sha256_on_export"] == ref.get("sha256")
        written.append(name)
    (case_dir / "case.json").write_text(json.dumps({**case, "artifacts": refs}, indent=1),
                                        encoding="utf-8")
    written.append("case.json")
    return written

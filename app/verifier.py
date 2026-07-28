"""Deterministic verification (§4.3) — the only code permitted to set a success status.

Three properties matter more than the details:

**It re-extracts, it does not re-read.** The verifier parses the stored artifact with lxml
and resolves the anchors the plan froze, independently of whatever the executor's live DOM
query returned. Then it compares. A verifier that reads the executor's own value back is a
formality; this one has caught the executor being wrong (see the replay suite).

**It runs on the full artifact** (A7.4), never on the reduced view a model was shown.
Verifying against the trimmed page would make verification circular.

**It binds values to labels structurally** (S-4.9). Checking that a value *looks like* a
product code is not verification — every wrong answer on a well-formed page also looks like
a product code. The value must be reachable from its label by a declared relation.

The two defects that shipped from M1 are the reference cases: both runs had the right step
count, the right artifact count and a clean terminal status, and both answered a different
question than the one asked. Nothing structural distinguishes them from a correct run. Only
re-extraction against a frozen question does.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from lxml import html as lxml_html

from app.evidence import EvidenceBundle
from app.identity import ElementIdentity
from app.models import FailureClass, Run, StepKind, TerminalStatus
from app.postcondition import AbsenceMode, ClaimSpec, Postcondition, Relation, matches_frozen
from app.records import host_key, named_site
from app.store import Store

WS = re.compile(r"\s+")
COUNTER = re.compile(
    r"^\s*(?P<count>\d+)\s+results?"
    r"(?:\s+for\s+[\"“](?P<term>.*?)[\"”])?"
    r"(?:\s*[-–]\s*showing\s+(?P<first>\d+)\s+to\s+(?P<last>\d+))?",
    re.IGNORECASE)
PAGER = re.compile(r"page\s+(?P<page>\d+)\s+of\s+(?P<total>\d+)"
                   r"(?:\s*[·•]\s*(?P<items>\d+)\s+products?)?", re.IGNORECASE)
MONEY = re.compile(r"[£$€]\s*([0-9]+(?:\.[0-9]+)?)")


class AnchorNotFound(Exception):
    """The declared label or container did not resolve in the stored artifact."""


class AnchorAmbiguous(Exception):
    """The label resolved to several places that disagree. Picking one would be a guess."""


def norm(text: str) -> str:
    return WS.sub(" ", (text or "")).strip()


@dataclass
class Check:
    name: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class ClaimResult:
    name: str
    ok: bool
    failure_class: FailureClass | None = None
    reason: str = ""
    evidence: EvidenceBundle | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "failure_class": self.failure_class.value if self.failure_class else None,
            "reason": self.reason,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass
class Verdict:
    status: TerminalStatus
    failure_class: FailureClass | None
    explanation: str
    checks: list[Check] = field(default_factory=list)
    claims: list[ClaimResult] = field(default_factory=list)

    @property
    def counts_as_success(self) -> bool:
        from app.models import counts_as_success
        return counts_as_success(self.status)

    @property
    def evidence_summary(self) -> dict[str, Any]:
        """How much was actually re-examined, with the unexamined named (A17.6).

        A claim only counts as independently checked when the verifier re-resolved its
        anchor in the stored artifact and compared the value it read against the run's. A
        count that includes claims nobody could re-resolve is a count of checks that did not
        happen, which is the same defect as a postcondition with no claims in it.
        """
        checked = [c.name for c in self.claims if c.ok]
        unchecked = [{"claim": c.name,
                      "why": c.reason or "not re-resolved against the artifact"}
                     for c in self.claims if not c.ok]
        return {"claims": len(self.claims), "independently_checked": len(checked),
                "checked": checked, "unchecked": unchecked}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "failure_class": self.failure_class.value if self.failure_class else None,
            "explanation": self.explanation,
            "counts_as_success": self.counts_as_success,
            "evidence_summary": self.evidence_summary,
            "checks": [c.to_dict() for c in self.checks],
            "claims": [c.to_dict() for c in self.claims],
        }


class Verifier:
    def __init__(self, store: Store) -> None:
        self._store = store

    def missing_actions(self, run: Run, pc: Postcondition) -> list[str]:
        """Which declared actions the trace does not show, asked before the run has ended.

        The executor needs the same answer mid-run to decide whether it may stop early, and
        it must be the *same* answer — a loop that used a looser rule than the verifier
        would stop on runs the verifier then fails.
        """
        return _missing_actions(run, pc)

    # ---- entry point -----------------------------------------------------------

    def verify(self, run: Run, *, artifact_id: str | None,
               candidate: dict[str, Any]) -> Verdict:
        checks: list[Check] = []

        if not matches_frozen(run.postcondition, run.postcondition_hash):
            checks.append(Check("postcondition_frozen", False,
                                {"recorded_hash": run.postcondition_hash}))
            return Verdict(
                TerminalStatus.FAILED, FailureClass.VERIFICATION_MISMATCH,
                "The postcondition verification ran against is not the one frozen at plan "
                "time — its hash does not match what the trace recorded. Divergence is "
                "itself a failure: it means the bar could have moved during the run.",
                checks)
        pc = _rehydrate(run.postcondition or {})
        checks.append(Check("postcondition_frozen", True,
                            {"hash": run.postcondition_hash, "operation": pc.operation}))

        ref = self._store.get_artifact_ref(artifact_id) if artifact_id else None
        if ref is None or ref.state != "stored":
            checks.append(Check("artifact_available", False,
                                {"artifact_id": artifact_id,
                                 "state": ref.state if ref else "missing"}))
            return Verdict(
                TerminalStatus.FAILED, FailureClass.INTERNAL_ERROR,
                "The artifact this claim would be verified against is not readable, so no "
                "claim can be confirmed. Reporting an unverified answer instead would be "
                "the silent failure this system exists to avoid.", checks)
        raw = self._store.read_artifact(ref.id)
        if raw is None:
            checks.append(Check("artifact_available", False, {"artifact_id": ref.id}))
            return Verdict(TerminalStatus.FAILED, FailureClass.INTERNAL_ERROR,
                           "The artifact record exists but its bytes could not be read.",
                           checks)
        checks.append(Check("artifact_available", True, ref.to_dict()))

        wrong_site = self._named_site(run, pc, ref, checks)
        if wrong_site is not None:
            return wrong_site

        # A run that navigated somewhere else answers a different question, however clean
        # its trace looks. This check is what catches a mis-routed plan.
        #
        # An undeclared task freezes the *site* instead of the page: nobody knows which page
        # of an unseen site holds the answer, so demanding the entry page would fail every
        # honest run that navigated once. It is a weaker constraint that still catches the
        # failure it exists for — evidence produced somewhere the task never named.
        scope = (pc.inputs or {}).get("url_scope")
        if scope == "prefix":
            # The operation names a section of a site, not one page: which page inside it
            # holds the answer is what the run is for. Still a real constraint — evidence
            # from outside the section is still rejected.
            inside = (ref.source_url or "").startswith(pc.target_url)
            checks.append(Check("artifact_source_matches_plan", inside,
                                {"artifact_source_url": ref.source_url,
                                 "plan_target_prefix": pc.target_url, "scope": "prefix"}))
            if not inside:
                return Verdict(
                    TerminalStatus.FAILED, FailureClass.VERIFICATION_MISMATCH,
                    f"The evidence was captured on {ref.source_url}, which is not inside "
                    f"{pc.target_url}.", checks)
        site_scope = scope == "site"
        if site_scope and not _same_site(ref.source_url, pc.target_url):
            checks.append(Check("artifact_source_matches_plan", False,
                                {"artifact_source_url": ref.source_url,
                                 "plan_target_site": pc.target_url, "scope": "site"}))
            return Verdict(
                TerminalStatus.FAILED, FailureClass.VERIFICATION_MISMATCH,
                f"The evidence was captured on {ref.source_url}, which is not on the site "
                f"the task named ({pc.target_url}).", checks)
        redirect = _followed_redirect(run, ref.source_url, pc.target_url)
        if scope is None and redirect:
            # The run asked for the frozen URL and the site sent it somewhere else. That is
            # the site's decision, recorded in the trace with both URLs, and rejecting it
            # would fail every correct run on an article title that redirects.
            checks.append(Check("artifact_source_matches_plan", True,
                                {"requested": pc.target_url, "redirected_to": redirect,
                                 "source_url": ref.source_url}))
        elif scope is None and not _same_page(ref.source_url, pc.target_url):
            checks.append(Check("artifact_source_matches_plan", False,
                                {"artifact_source_url": ref.source_url,
                                 "plan_target_url": pc.target_url}))
            return Verdict(
                TerminalStatus.FAILED, FailureClass.VERIFICATION_MISMATCH,
                f"The evidence was captured on {ref.source_url}, but the plan targeted "
                f"{pc.target_url}. Whatever the page said, it is not an answer to the task "
                f"that was frozen at plan time.", checks)
        checks.append(Check("artifact_source_matches_plan", True,
                            {"source_url": ref.source_url}))

        missing = _missing_actions(run, pc)
        if missing:
            checks.append(Check("required_actions_present", False, {"missing": missing}))
            return Verdict(
                TerminalStatus.FAILED, FailureClass.REQUIRED_ACTION_SKIPPED,
                f"The plan declared {len(pc.required_actions)} required action(s) and the "
                f"trace does not show {', '.join(missing)}. A right answer reached without "
                f"the declared action is scored as a failure (S-4.4), because the capability "
                f"being claimed is the interaction, not the value.", checks)
        checks.append(Check("required_actions_present", True,
                            {"actions": [a.to_dict() for a in pc.required_actions]}))

        tree = lxml_html.fromstring(raw.decode("utf-8", "replace"))
        segment = [t.seq for t in run.trace if t.kind in (StepKind.CLICK, StepKind.FILL,
                                                          StepKind.EXTRACT, StepKind.SNAPSHOT)]

        results: list[ClaimResult] = []
        by_relation: dict[Relation, Any] = {}
        for spec in pc.claims:
            result, value = self._verify_claim(spec, tree, ref, candidate, segment, pc)
            results.append(result)
            if result.ok:
                by_relation[spec.relation] = value

        return self._decide(pc, results, by_relation, checks, candidate)

    def _named_site(self, run: Run, pc: Postcondition, ref,
                    checks: list[Check]) -> Verdict | None:
        """Reject evidence collected somewhere other than the site the task named (A17.1).

        The site is read from the task text here, by this code, and compared against the
        origin the artifact actually came from. Routing made the same reading earlier to
        decide where to go; that reading is frozen in the postcondition and compared too, so
        a plan that went somewhere else *and* recorded that it had is caught by the
        disagreement rather than believed.

        This is not a second copy of the router's check. The router decides which operations
        a task may reach; nothing in it looks at where the evidence came from, and a
        correctly routed plan with a wrong URL in it passes every routing check there is.
        """
        expected = named_site(run.task)
        frozen = pc.named_site
        if frozen and expected and host_key(frozen) != host_key(expected):
            checks.append(Check("named_site_frozen", False,
                                {"frozen_at_plan_time": frozen, "task_names": expected}))
            return Verdict(
                TerminalStatus.FAILED, FailureClass.VERIFICATION_MISMATCH,
                f"The plan froze {frozen!r} as the site this task named, and the task names "
                f"{expected!r}. The postcondition is what verification is measured against, "
                f"so a postcondition about a different site cannot certify this run.", checks)
        if not expected:
            checks.append(Check("named_site_frozen", True,
                                {"task_names": None,
                                 "note": "the task names no site, so this constraint is "
                                         "absent; the frozen target URL still applies"}))
            return None
        origin = host_key(urlsplit(ref.source_url or "").netloc)
        ok = origin == host_key(expected)
        checks.append(Check("artifact_origin_is_the_named_site", ok,
                            {"task_names": expected, "artifact_origin": origin,
                             "frozen_at_plan_time": frozen or None,
                             "artifact_source_url": ref.source_url}))
        if ok:
            return None
        return Verdict(
            TerminalStatus.FAILED, FailureClass.VERIFICATION_MISMATCH,
            f"The task names {expected}, and the evidence was collected on "
            f"{origin or 'nowhere resolvable'} ({ref.source_url}). Everything else about "
            f"this run may be correct — the interaction, the anchors, the values — and it "
            f"still answers a question about a different site, which is the worst outcome "
            f"this system can produce rather than a technicality.", checks)

    # ---- one claim -------------------------------------------------------------

    def _verify_claim(self, spec: ClaimSpec, tree, ref, candidate: dict[str, Any],
                      segment: list[int], pc: Postcondition
                      ) -> tuple[ClaimResult, Any]:
        try:
            value, span, anchor = self._extract(spec, tree, candidate)
        except AnchorNotFound as exc:
            if spec.relation is Relation.ELEMENT_ABSENT:
                # The anchor resolving is the failure here: the element that had to be gone
                # is still in the artifact, so the state transition never happened.
                return ClaimResult(spec.name, False, FailureClass.POSTCONDITION_UNMET,
                                   str(exc)), None
            return ClaimResult(spec.name, False, FailureClass.LOCATOR_NOT_FOUND,
                               f"{exc}. The value may well be on the page, but it could not "
                               f"be reached from its declared label, so it is not bound to "
                               f"anything and cannot be confirmed."), None
        except AnchorAmbiguous as exc:
            return ClaimResult(spec.name, False, FailureClass.VERIFICATION_MISMATCH,
                               f"{exc}"), None

        bundle = EvidenceBundle(
            claim=spec.name, artifact_id=ref.id, source_url=ref.source_url,
            retrieved_at=ref.retrieved_at, artifact_sha256=ref.sha256,
            structural_anchor=anchor, label_anchor=spec.label, extracted_span=span,
            normalised_value=value, trace_segment=segment, artifact_state=ref.state)

        mine = _coerce(value, spec.value_type)
        bundle.normalised_value = mine

        # Did the page answer the question that was frozen, or a neighbouring one? This is
        # the check the M1 search defect needed and did not have: a mangled term produces a
        # real results page with a real count, and every structural property of the run is
        # correct. Only the page's own echo of the query, compared against the frozen input,
        # separates "no matches" from "we asked something else".
        drift = frozen_input_drift(spec, value, pc)
        if drift:
            return ClaimResult(spec.name, False, FailureClass.VERIFICATION_MISMATCH,
                               drift, bundle), None

        if spec.name not in candidate:
            return ClaimResult(
                spec.name, False, FailureClass.VERIFICATION_MISMATCH,
                "The run produced no candidate for this claim, so there is nothing to "
                "compare the re-extracted value against. Verification compares two "
                "independent readings; one reading is not a verification.", bundle), None

        theirs = _coerce(candidate[spec.name], spec.value_type)
        if theirs != mine:
            return ClaimResult(
                spec.name, False, FailureClass.VERIFICATION_MISMATCH,
                f"Re-extraction from the stored artifact gives {mine!r}; the run reported "
                f"{theirs!r}.", bundle), None
        return ClaimResult(spec.name, True, None, "", bundle), value

    def _extract(self, spec: ClaimSpec, tree,
                 candidate: dict[str, Any]) -> tuple[Any, str, str]:
        if spec.relation is Relation.LOCATED_LABEL:
            return _located_label(tree, spec, candidate)
        if spec.relation is Relation.TABLE_ROW_CELL:
            return _table_row_cell(tree, spec)
        if spec.relation is Relation.COUNTER_ECHO:
            return _counter_echo(tree, spec)
        if spec.relation is Relation.EMPTY_STATE:
            return _empty_state(tree, spec)
        if spec.relation is Relation.PAGER_POSITION:
            return _pager_position(tree, spec)
        if spec.relation is Relation.LIST_ENUMERATION:
            return _list_enumeration(tree, spec)
        if spec.relation is Relation.ELEMENT_ABSENT:
            return _element_absent(tree, spec)
        if spec.relation is Relation.TABLE_COLUMN_CELL:
            return _table_column_cell(tree, spec)
        if spec.relation is Relation.SORT_STATE:
            return _sort_state(tree, spec)
        if spec.relation is Relation.TABLE_TOP_ROW:
            return _table_top_row(tree, spec)
        raise AnchorNotFound(f"No extractor for relation {spec.relation}")

    # ---- status decision -------------------------------------------------------

    def _decide(self, pc: Postcondition, results: list[ClaimResult],
                extracted: dict[Relation, Any], checks: list[Check],
                candidate: dict[str, Any] | None = None) -> Verdict:
        # A11.7: a verification that passes because there was nothing to check is a
        # defect, not a pass. Each of these is a way for a run to be "clean" without any
        # evidence having been examined, and a vacuous success is indistinguishable from a
        # real one in every aggregate — which is the silent failure §4 exists to prevent.
        vacuous = self._vacuous(pc, results, checks)
        if vacuous:
            return Verdict(TerminalStatus.FAILED, FailureClass.POSTCONDITION_UNMET,
                           vacuous, checks, results)

        hard = [r for r in results if not r.ok and r.failure_class in
                (FailureClass.VERIFICATION_MISMATCH, FailureClass.POSTCONDITION_UNMET)]
        if hard:
            return Verdict(TerminalStatus.FAILED, hard[0].failure_class,
                           "; ".join(f"{r.name}: {r.reason}" for r in hard),
                           checks, results)

        absence = self._absence(pc, extracted, checks, candidate)
        if absence is not None:
            return Verdict(absence[0], absence[1], absence[2], checks, results)

        required = [r for r in results if not _optional(pc, r.name)]
        verified = [r for r in required if r.ok]
        if len(verified) == len(required):
            return Verdict(
                TerminalStatus.SUCCEEDED_VERIFIED, None,
                f"All {len(required)} required claims were re-extracted from the stored "
                f"artifact through their declared label anchors and matched the run's "
                f"values. Verified means consistent with the artifact preserved at capture "
                f"time — not true in the world.", checks, results)
        if verified:
            failed = [r.name for r in required if not r.ok]
            return Verdict(
                TerminalStatus.PARTIAL, FailureClass.LOCATOR_NOT_FOUND,
                f"{len(verified)} of {len(required)} required claims verified; "
                f"{', '.join(failed)} could not be bound to a label in the stored artifact. "
                f"Partial is not a success state and is never counted as one.",
                checks, results)
        return Verdict(
            TerminalStatus.FAILED, FailureClass.LOCATOR_NOT_FOUND,
            "Not one declared anchor resolved in the stored artifact, so no claim was "
            "examined at all. That is a failed verification, not an unverified answer: "
            "nothing was checked (A11.7).", checks, results)

    @staticmethod
    def _vacuous(pc: Postcondition, results: list[ClaimResult],
                 checks: list[Check]) -> str:
        """The reason this verification would be empty, or "" if it has real work to do.

        Kept as one function so the rule is stated once. Adding a verification path means
        deciding what its vacuous case looks like, here, rather than discovering later that
        it passes by default.
        """
        if not pc.claims:
            return ("The frozen postcondition declares no claims, so there was nothing to "
                    "verify. \"Nothing failed\" is not \"everything passed\".")
        if all(c.optional for c in pc.claims):
            return (f"All {len(pc.claims)} declared claims are optional, so this run could "
                    f"reach a success status without a single value being confirmed.")
        if not checks:
            return "No verification check ran at all."
        if all(not c.ok for c in checks):
            return "Every verification check was skipped or failed."
        return ""

    def _absence(self, pc: Postcondition, extracted: dict[Relation, Any],
                 checks: list[Check], candidate: dict[str, Any] | None = None
                 ) -> tuple[TerminalStatus, FailureClass | None, str] | None:
        """Absence is only ever concluded from a positive proof (Amendment 3)."""
        counter = extracted.get(Relation.COUNTER_ECHO)
        enumerated = extracted.get(Relation.LIST_ENUMERATION)
        empty_seen = extracted.get(Relation.EMPTY_STATE) is True

        is_empty_result = isinstance(counter, dict) and counter.get("count") == 0
        predicate = pc.inputs.get("predicate")

        if is_empty_result:
            if pc.absence is AbsenceMode.A_EMPTY_STATE and empty_seen:
                checks.append(Check("absence_mode_a", True,
                                    {"empty_state_element": True,
                                     "echoed_term": counter.get("term")}))
                return (TerminalStatus.NO_RESULT_VERIFIED, None,
                        f"Nothing matched, and that is proven rather than assumed: the page "
                        f"states it in a located empty-state element, and the counter echoes "
                        f"the term {counter.get('term')!r} that was frozen at plan time.")
            checks.append(Check("absence_mode_a", False,
                                {"empty_state_element": empty_seen,
                                 "declared_mode": pc.absence.value}))
            return (TerminalStatus.UNVERIFIED, FailureClass.POSTCONDITION_UNMET,
                    "The result set is empty but no empty-state element was located, so "
                    "absence is not proven. \"I looked and did not find it\" is never "
                    "no_result_verified (A3.2).")

        if predicate and isinstance(enumerated, list):
            # The predicate and the domain it ranges over were frozen before any member was
            # seen — the hash check at the top of `verify` is what makes that checkable.
            # A predicate assembled after the results are in is not a postcondition.
            domain = next((c.container for c in pc.claims
                           if c.relation is Relation.LIST_ENUMERATION), "")
            checks.append(Check("enumeration_predicate_frozen", True,
                                {"predicate": predicate, "domain": domain,
                                 "frozen_by": "postcondition_frozen"}))
            # Either form of the site's own count is a coverage anchor. A3.2 names both —
            # "110 results - showing 1 to 20." and "Page 1 of 6" — and a category that fits
            # on one page has no pager at all, so requiring the pager would make single-page
            # absence unprovable on a site that states its total plainly.
            pager = extracted.get(Relation.PAGER_POSITION)
            total, anchor_kind = None, None
            if isinstance(pager, dict) and pager.get("items") is not None:
                total, anchor_kind = pager["items"], "pager total"
            elif isinstance(counter, dict) and counter.get("count") is not None:
                total, anchor_kind = counter["count"], "results counter"
            matches = [i for i in enumerated if _predicate_holds(i, predicate)]
            found = sorted(str(m.get("sku")) for m in matches)
            complete = total is not None and total == len(enumerated)

            # The anchor is required in *both* directions (A17.12). "Yes, these two" is a
            # claim about the whole set — it says exactly two, not at least two — and
            # without proof that the enumeration was the whole set the honest reading is an
            # existence claim, which is weaker than the question asked for.
            if total is None or not pc.coverage_anchor or not complete:
                checks.append(Check("absence_mode_b_coverage", False,
                                    {"coverage_anchor": pc.coverage_anchor,
                                     "anchor_kind": anchor_kind, "anchor_total": total,
                                     "enumerated": len(enumerated),
                                     "matches_seen": found}))
                seen = (f"The site's own count says {total} items; {len(enumerated)} were "
                        f"enumerated from the artifact. "
                        if total is not None else
                        "No coverage anchor was located, so nothing states how large the "
                        "result set is. ")
                if matches:
                    return (TerminalStatus.UNVERIFIED, FailureClass.POSTCONDITION_UNMET,
                            f"{seen}At least {len(matches)} of the {len(enumerated)} items "
                            f"read from the artifact satisfy the frozen predicate "
                            f"({', '.join(found)}). That is an existence claim and it is "
                            f"reported as one: without a coverage anchor there is no proof "
                            f"the enumeration was the whole set, so \"exactly "
                            f"{len(matches)}\" is not established and this is not a "
                            f"complete answer to the question that was asked (A3.2).")
                return (TerminalStatus.UNVERIFIED, FailureClass.POSTCONDITION_UNMET,
                        f"{seen}Absence by enumeration requires a coverage anchor proving "
                        f"the whole result set was seen (A3.2). Without one this is only "
                        f"\"we did not happen to see it\".")
            checks.append(Check("absence_mode_b_coverage", complete,
                                {"anchor_total": total, "enumerated": len(enumerated),
                                 "anchor": pc.coverage_anchor,
                                 "anchor_kind": anchor_kind}))
            claimed = (candidate or {}).get("matches")
            if claimed is None:
                # A plan that does not say what it found can only be believed about absence,
                # so a match is a contradiction of the only thing it asserted.
                if matches:
                    checks.append(Check("absence_mode_b_predicate", False,
                                        {"matches": found}))
                    return (TerminalStatus.FAILED, FailureClass.VERIFICATION_MISMATCH,
                            f"The run claimed nothing matched, but re-checking every "
                            f"enumerated member found {len(matches)}: {', '.join(found)}.")
            else:
                # The run stated its own finding, so the two can be compared. This is a
                # stronger check than absence alone: it catches a run that enumerated
                # correctly and read the predicate the other way round.
                stated = sorted(str(c) for c in claimed)
                if stated != found:
                    checks.append(Check("enumeration_agreement", False,
                                        {"run_reported": stated, "artifact_says": found}))
                    return (TerminalStatus.FAILED, FailureClass.VERIFICATION_MISMATCH,
                            f"The run reported {len(stated)} match(es) and re-extraction "
                            f"from the stored artifact finds {len(found)}. Run: "
                            f"{', '.join(stated) or 'none'}. Artifact: "
                            f"{', '.join(found) or 'none'}.")
                checks.append(Check("enumeration_agreement", True, {"matches": found}))
                if matches:
                    return (TerminalStatus.SUCCEEDED_VERIFIED, None,
                            f"{len(matches)} of the {total} items in the complete listing "
                            f"satisfy the frozen predicate: {', '.join(found)}. Coverage is "
                            f"proven by the site's own anchor ({pc.coverage_anchor}), and "
                            f"every member was re-read from the stored artifact.")
            checks.append(Check("absence_mode_b_predicate", True,
                                {"checked": len(enumerated)}))
            return (TerminalStatus.NO_RESULT_VERIFIED, None,
                    f"Nothing matches, proven by enumeration: the site's own anchor "
                    f"({pc.coverage_anchor}) says {total} items, all {len(enumerated)} were "
                    f"re-read from the stored artifact, and none satisfies the frozen "
                    f"predicate.")
        return None


# ---- extractors ----------------------------------------------------------------
# Each returns (normalised value, verbatim span, the path that was re-resolved).

def _innermost(tree, pattern: re.Pattern) -> list[Any]:
    """Elements whose own text matches, with ancestors that only match through a child
    dropped. Matching `<html>` because the phrase appears somewhere inside it is not an
    anchor."""
    hits = [el for el in tree.iter() if isinstance(el.tag, str)
            and pattern.search(norm(el.text_content()))]
    hit_ids = {id(el) for el in hits}
    return [el for el in hits
            if not any(id(child) in hit_ids for child in el.iterdescendants())]


def _table_row_cell(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    xpath = ('//tr[th[normalize-space(.)=$label]]/td[1] '
             '| //tr[td[1][normalize-space(.)=$label]]/td[2]')
    cells = tree.xpath(xpath, label=spec.label)
    if not cells:
        raise AnchorNotFound(f"No row whose header cell reads {spec.label!r}")
    values = {norm(c.text_content()) for c in cells}
    if len(values) > 1:
        raise AnchorAmbiguous(
            f"The label {spec.label!r} appears in {len(cells)} rows with different values "
            f"({sorted(values)}). Choosing one would be a guess.")
    span = norm(cells[0].text_content())
    return _coerce(span, spec.value_type), span, f"{xpath} [label={spec.label!r}]"


def _counter_echo(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    for el in _innermost(tree, COUNTER):
        span = norm(el.text_content())
        m = COUNTER.search(span)
        if m:
            value = {"count": int(m.group("count")), "term": m.group("term")}
            if m.group("first"):
                value["showing"] = [int(m.group("first")), int(m.group("last"))]
            return (value,
                    span, f"//*[matches(., '{COUNTER.pattern}')] [label={spec.label!r}]")
    raise AnchorNotFound(f"No element states a result count in the form {spec.label!r}")


def _empty_state(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    needle = spec.label.lower()
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue
        text = norm(el.text_content())
        if needle in text.lower() and len(text) < 200:
            return True, text, f"//*[contains(., {spec.label!r})]"
    raise AnchorNotFound(f"No empty-state element containing {spec.label!r}")


def _pager_position(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    for el in _innermost(tree, PAGER):
        span = norm(el.text_content())
        m = PAGER.search(span)
        if m:
            return ({"page": int(m.group("page")), "total": int(m.group("total")),
                     "items": int(m.group("items")) if m.group("items") else None},
                    span, f"//*[matches(., 'Page N of M')] [label={spec.label!r}]")
    raise AnchorNotFound(f"No pager position element ({spec.label!r})")


def _list_enumeration(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    if not spec.container:
        raise AnchorNotFound("List enumeration requires a declared container")
    rows = tree.xpath(spec.container)
    if not rows:
        raise AnchorNotFound(f"Container {spec.container!r} resolved to nothing")
    items = []
    for row in rows:
        text = norm(row.text_content())
        money = MONEY.search(text)
        # An identifier if the markup offers one, otherwise the element's own title or
        # text. A list of products and a list of article titles are the same shape of
        # claim; only the fixture happens to carry SKUs.
        # A listing entry usually names itself on a nested link's `title` before it names
        # itself anywhere else. Without that step the identifier for a book was the whole
        # row — price, stock and basket button included — which is unreadable in an
        # explanation and impossible for a run to reproduce exactly.
        nested = row.xpath(".//*[@title][1]/@title")
        items.append({"sku": (row.get("data-sku") or _sku_from_text(text)
                              or row.get("title")
                              or (norm(nested[0]) if nested else None)
                              or text or None),
                      "text": text,
                      "price_gbp": float(money.group(1)) if money else None})
    return items, f"{len(items)} rows", spec.container


#: How tables on the web state their own sort direction, most standard first. This is a list
#: of conventions rather than a rule about any one site: `aria-sort` is the accessibility
#: standard, and the class names below are what the widely used table sorters emit when they
#: have no `aria-sort`. Reading the direction off the page is the whole point — the
#: alternative is assuming what a click produced, which is the error this claim exists to
#: catch.
SORT_DIRECTION_CLASSES = (
    ("headersortup", "ascending"), ("headersortdown", "descending"),      # MediaWiki
    ("sorting_asc", "ascending"), ("sorting_desc", "descending"),         # DataTables
    ("sorted-asc", "ascending"), ("sorted-desc", "descending"),
    ("tablesorter-headerasc", "ascending"), ("tablesorter-headerdesc", "descending"),
)


def _header_cells(tree, spec: ClaimSpec) -> list[Any]:
    """Every column header matching the claim's label, inside the declared container."""
    scope = tree.xpath(spec.container) if spec.container else [tree]
    if not scope:
        raise AnchorNotFound(f"Container {spec.container!r} resolved to nothing")
    found = []
    for node in scope:
        found.extend(th for th in node.xpath(".//tr/th")
                     if norm(th.text_content()) == spec.label)
    if not found:
        # A person writes "by country"; the header reads "Country/Territory". A unique
        # prefix is the same column named shorter — more than one is a choice we refuse to
        # make, which is the existing rule for an ambiguous anchor.
        prefixed = {}
        for node in scope:
            for th in node.xpath(".//tr/th"):
                text = norm(th.text_content())
                if text.lower().startswith(spec.label.lower()) and spec.label:
                    prefixed.setdefault(text, []).append(th)
        if len(prefixed) == 1:
            return next(iter(prefixed.values()))
        if len(prefixed) > 1:
            raise AnchorAmbiguous(
                f"{spec.label!r} is the start of {len(prefixed)} different column headers "
                f"({sorted(prefixed)}). Choosing one would be a guess.")
        raise AnchorNotFound(
            f"No column header reads {spec.label!r} inside {spec.container or 'the page'}")
    return found


def _column_index(header) -> int:
    """The header's position among the cells of its own row, counting spans."""
    index = 0
    for cell in header.getparent().xpath("./th|./td"):
        if cell is header:
            return index
        try:
            index += int(cell.get("colspan", 1))
        except ValueError:
            index += 1
    return index


def _table_column_cell(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    """The cell in the first data row, under the named column header.

    The row is the one the *page* put first, re-read from the stored artifact. Whether the
    sort was supposed to produce that row is a separate claim; this one only reports what is
    there, so an extra or missing click shows up as a value that does not match rather than
    as a check that quietly adapts.
    """
    values: dict[str, Any] = {}
    for header in _header_cells(tree, spec):
        index = _column_index(header)
        table = header.xpath("ancestor::table[1]")
        rows = table[0].xpath(".//tr[td]") if table else []
        if not rows:
            continue
        cells = rows[0].xpath("./th|./td")
        if index < len(cells):
            values[norm(cells[index].text_content())] = index
    if not values:
        raise AnchorNotFound(
            f"The column {spec.label!r} was found but its table has no data rows")
    if len(values) > 1:
        raise AnchorAmbiguous(
            f"The column header {spec.label!r} appears in more than one table with "
            f"different top-row values ({sorted(values)}). Choosing one would be a guess.")
    span = next(iter(values))
    return (_coerce(span, spec.value_type), span,
            f"{spec.container or '//table'}//tr[td][1]/td[column={spec.label!r}]")


def _table_top_row(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    """The first data row of the table carrying the named header, cell by cell, each one
    bound to its own column header.

    Reporting the row rather than one column of it is what lets an operation answer a
    question about a column nobody declared in advance — and every cell is still bound
    structurally, so it is a wider answer, not a looser one.
    """
    headers = _header_cells(tree, spec)
    rows_by_table = {}
    for header in headers:
        table = header.xpath("ancestor::table[1]")
        if not table:
            continue
        data_rows = table[0].xpath(".//tr[td]")
        if not data_rows:
            continue
        names = [norm(c.text_content())
                 for c in table[0].xpath(".//tr[th]")[0].xpath("./th|./td")]
        cells = data_rows[0].xpath("./th|./td")
        row = {name: norm(cell.text_content())
               for name, cell in zip(names, cells) if name}
        if row:
            rows_by_table[json.dumps(row, sort_keys=True)] = row
    if not rows_by_table:
        raise AnchorNotFound(
            f"The column {spec.label!r} was found but its table has no readable data row")
    if len(rows_by_table) > 1:
        raise AnchorAmbiguous(
            f"The column header {spec.label!r} appears in more than one table with "
            f"different top rows. Choosing one would be a guess.")
    row = next(iter(rows_by_table.values()))
    span = " | ".join(f"{k}: {v}" for k, v in row.items())
    return row, span[:400], f"table with header {spec.label!r} → first data row"


def _sort_state(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    """What the table says about how it is currently ordered."""
    states = set()
    index = None
    for header in _header_cells(tree, spec):
        classes = (header.get("class") or "").lower()
        aria = (header.get("aria-sort") or "").strip().lower()
        direction = aria if aria in ("ascending", "descending") else "unsorted"
        if direction == "unsorted":
            for marker, named in SORT_DIRECTION_CLASSES:
                if marker in classes:
                    direction = named
                    break
        states.add(direction)
        index = _column_index(header)
    if len(states) > 1:
        raise AnchorAmbiguous(
            f"The column header {spec.label!r} appears more than once with different sort "
            f"states ({sorted(states)}).")
    direction = next(iter(states))
    value = {"column": spec.label, "direction": direction, "column_index": index}
    return value, f"{spec.label}: {direction}", f"th[text()={spec.label!r}]/@class|@aria-sort"


#: Anchor suffix a claim's located label is carried under in the candidate. The value and
#: the label it was read from travel together or the pair means nothing.
ANCHOR_SUFFIX = "_anchor"


def _bound_to(label_element) -> list[tuple[str, str]]:
    """What a label element binds to, by structure only — (value, how it was reached).

    The same relations S-4.9 names, applied without knowing the site in advance: a header
    cell binds the data cell of its row, a `dt` binds its `dd`, a `label[for]` binds the
    control it names, and anything else binds its next element sibling. Nothing here reads
    proximity on screen or the order of the document at large.
    """
    tag = label_element.tag if isinstance(label_element.tag, str) else ""
    found: list[tuple[str, str]] = []
    if tag in ("th", "td"):
        row = label_element.getparent()
        if row is not None and row.tag == "tr":
            cells = row.xpath("./th|./td")
            index = cells.index(label_element)
            if index + 1 < len(cells):
                found.append((norm(cells[index + 1].text_content()), "same row, next cell"))
    if tag == "dt":
        sibling = label_element.getnext()
        if sibling is not None and sibling.tag == "dd":
            found.append((norm(sibling.text_content()), "dt → dd"))
    if tag == "label" and label_element.get("for"):
        for target in label_element.xpath(f'//*[@id=$id]', id=label_element.get("for")):
            found.append((norm(target.get("value") or target.text_content()),
                          "label[for] → control"))
    if not found:
        sibling = label_element.getnext()
        if sibling is not None and isinstance(sibling.tag, str):
            found.append((norm(sibling.text_content()), "next element sibling"))
    return [(value, how) for value, how in found if value]


def _located_label(tree, spec: ClaimSpec, candidate: dict[str, Any]) -> tuple[Any, str, str]:
    """Re-resolve the label the run located, and read what is bound to it (A13.2.3).

    The run says "the answer is X, and I read it next to the label L". This finds L in the
    stored artifact and reads what is bound to it independently. The model chose where to
    look; it does not get to decide what was there.
    """
    wanted = norm(str(candidate.get(spec.name + ANCHOR_SUFFIX, "")))
    if not wanted:
        raise AnchorNotFound(
            "The run produced no label for this claim, so there is nothing to bind the "
            "value to. An answer with no anchor is a reading, not a verification")
    matches = [el for el in tree.iter()
               if isinstance(el.tag, str)
               and norm(el.text_content()).lower() == wanted.lower()
               and not any(norm(child.text_content()).lower() == wanted.lower()
                           for child in el.iterdescendants() if isinstance(child.tag, str))]
    if not matches:
        raise AnchorNotFound(f"No element in the artifact reads {wanted!r}")
    values = {}
    for element in matches:
        # A label is routinely wrapped — `<th><a>Stable release</a></th>` — and the link
        # binds to nothing, so the innermost match alone failed on every Wikipedia infobox
        # while the label was plainly there. Climb only while the enclosing element says
        # exactly the same thing, and stop at the first level that actually binds; going
        # all the way out reaches a container whose "next sibling" is unrelated.
        node = element
        while node is not None:
            bound = _bound_to(node)
            if bound:
                for value, how in bound:
                    values.setdefault(value, how)
                break
            parent = node.getparent()
            node = (parent if parent is not None and isinstance(parent.tag, str)
                    and norm(parent.text_content()).lower() == wanted.lower() else None)
    if not values:
        raise AnchorNotFound(
            f"The label {wanted!r} is in the artifact but nothing is structurally bound to "
            f"it, so the value beside it on screen cannot be tied to it")
    if len(values) > 1:
        raise AnchorAmbiguous(
            f"The label {wanted!r} binds to {len(values)} different values "
            f"({sorted(values)}). Choosing one would be a guess.")
    span, how = next(iter(values.items()))
    return _coerce(span, spec.value_type), span, f"label({wanted!r}) → {how}"


def _element_absent(tree, spec: ClaimSpec) -> tuple[Any, str, str]:
    found = tree.xpath(spec.container) if spec.container else []
    if found:
        raise AnchorNotFound(
            f"{spec.label} is still present in the artifact ({len(found)} node(s)), so the "
            f"state transition it was meant to evidence did not happen")
    return True, f"{spec.label}: absent", spec.container


SKU = re.compile(r"\b([A-Z]{2}-\d{3,5})\b")


def _sku_from_text(text: str) -> str | None:
    m = SKU.search(text)
    return m.group(1) if m else None


# ---- helpers -------------------------------------------------------------------

def _coerce(value: Any, value_type: str) -> Any:
    if value_type == "integer":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return int(value)
        m = re.search(r"-?\d+", str(value))
        return int(m.group(0)) if m else None
    if value_type == "money_gbp":
        if isinstance(value, (int, float)):
            return round(float(value), 2)
        m = MONEY.search(str(value)) or re.search(r"(\d+(?:\.\d+)?)", str(value))
        return round(float(m.group(1)), 2) if m else None
    if value_type == "code":
        return norm(str(value)).upper()
    if value_type == "text":
        return norm(str(value))
    if value_type == "text_list":
        if isinstance(value, list):
            return sorted(norm(str(v.get("sku") if isinstance(v, dict) else v)).casefold()
                          for v in value if v)
        return value
    if value_type == "ordered_text_list":
        # Order is the answer here, not a property of the page to be normalised away. A
        # sort that ran one click too few produces a perfectly reasonable list in the wrong
        # order, and sorting it before comparing would erase exactly that.
        if isinstance(value, list):
            return [norm(str(v.get("text") if isinstance(v, dict) else v)).casefold()
                    for v in value if v]
        return value
    if value_type == "row":
        # A header→cell mapping, compared cell by cell after whitespace normalisation. Both
        # readings come from the same table; what differs is when and by which code.
        if isinstance(value, dict):
            return {norm(str(k)): norm(str(v)) for k, v in value.items()}
        return value
    if value_type == "sku_list":
        # Compared as a set of identifiers: the run reports which items it saw, and order
        # is a property of the page rather than of the answer.
        if isinstance(value, list):
            return sorted(str(v.get("sku") if isinstance(v, dict) else v).upper()
                          for v in value if (v.get("sku") if isinstance(v, dict) else v))
        return value
    return value


def frozen_input_drift(spec: ClaimSpec, value: Any, pc: Postcondition) -> str:
    """Empty string when the page answered the frozen question, a reason when it did not."""
    if spec.relation is Relation.COUNTER_ECHO and "term" in pc.inputs:
        frozen = norm(str(pc.inputs["term"] or "")).casefold()
        echoed = norm(str(value.get("term") or "")).casefold()
        if frozen and echoed != frozen:
            return (f"The plan froze the term {frozen!r}, but the page states it answered "
                    f"{echoed!r}. The result set is real; it is a result set for a "
                    f"different question.")
    if spec.relation is Relation.PAGER_POSITION and "page" in pc.inputs:
        frozen_page = pc.inputs["page"]
        if frozen_page == "last":
            # "The last page" is a position the listing states, not a number the task can
            # give. The pager's own total is what settles whether the run got there.
            if value.get("page") != value.get("total"):
                return (f"The task asked for the last page; the pager states page "
                        f"{value.get('page')} of {value.get('total')}.")
            return ""
        if frozen_page is not None and value.get("page") != frozen_page:
            return (f"The plan froze page {frozen_page}, but the artifact shows page "
                    f"{value.get('page')} as the visible one.")
    if spec.relation is Relation.SORT_STATE and "direction" in pc.inputs:
        frozen = str(pc.inputs["direction"] or "").lower()
        echoed = str(value.get("direction") or "").lower()
        if frozen and echoed != frozen:
            return (f"The plan froze a {frozen} sort on {value.get('column')!r}, but the "
                    f"table states it is {echoed}. One click too few or too many produces a "
                    f"perfectly reasonable ordering of the wrong kind, and the table's own "
                    f"statement is what settles it.")
    return ""


def _same_page(source_url: str | None, target_url: str) -> bool:
    """Same origin and same path. Query strings differ legitimately (mutation seeds).

    Paths are compared percent-decoded. A plan freezes the escaped form it navigated to and
    the browser reports back whatever spelling it settled on — `List_of_S%26P_500_companies`
    against `List_of_S&P_500_companies` is one page written two ways, and treating it as two
    pages fails a correct run for a difference in encoding. The guard fails closed, so this
    was invisible until a target URL happened to contain an escape.
    """
    if not source_url:
        return False
    a, b = urlsplit(source_url), urlsplit(target_url)
    return ((a.scheme, a.netloc, unquote(a.path).rstrip("/"))
            == (b.scheme, b.netloc, unquote(b.path).rstrip("/")))


def _followed_redirect(run: Run, source_url: str | None, target_url: str) -> str:
    """The URL the site sent the run to after it asked for the frozen one, or "".

    Both are recorded on the navigation step, so this is the trace answering rather than an
    assumption that a difference must be benign. A run that navigated somewhere it was
    never sent still fails.
    """
    if not source_url or _same_page(source_url, target_url):
        return ""
    for entry in run.trace:
        if entry.kind is not StepKind.NAVIGATE:
            continue
        requested = str(entry.detail.get("url") or "")
        final = str(entry.detail.get("final_url") or "")
        if requested and final and _same_page(requested, target_url) \
                and _same_page(final, source_url):
            return final
    return ""


def _same_site(source_url: str | None, target_url: str) -> bool:
    """Same scheme and host. The constraint an undeclared task can honestly freeze.

    Host comparison ignores a leading `www.`, because the task names a site the way a
    person writes it and the site may answer on either spelling.
    """
    if not source_url:
        return False
    a, b = urlsplit(source_url), urlsplit(target_url)
    strip = lambda host: host.lower().removeprefix("www.")  # noqa: E731
    return a.scheme == b.scheme and strip(a.netloc) == strip(b.netloc)


def _missing_actions(run: Run, pc: Postcondition) -> list[str]:
    """Whether the trace shows each declared action happening.

    The same action can be reached two ways — the scripted path names `#next`, the planner
    names a ref that resolves to it — so both are rebuilt into the shared `ElementIdentity`
    and matched by its comparison. This function deliberately owns no list of fields of its
    own; the last three times it did, a run that took exactly the right action was scored as
    having skipped it.
    """
    missing = []
    for action in pc.required_actions:
        seen = 0
        for t in run.trace:
            if t.kind.value != action.kind or not t.ok:
                continue
            if ElementIdentity.from_trace(t.detail, t.summary).matches(action.target):
                seen += 1
        if seen < action.times:
            missing.append(f"{action.kind} on {action.target} "
                           f"({seen}/{action.times} observed)")
    return missing


def _optional(pc: Postcondition, name: str) -> bool:
    return any(c.optional for c in pc.claims if c.name == name)


def _predicate_holds(item: dict[str, Any], predicate: dict[str, Any]) -> bool:
    field_name, op, target = predicate.get("field"), predicate.get("op"), predicate.get("value")
    value = item.get(field_name)
    if value is None:
        return False
    if op == ">":
        return value > target
    if op == ">=":
        return value >= target
    if op == "<":
        return value < target
    if op == "<=":
        return value <= target
    if op == "==":
        return value == target
    if op == "contains":
        return str(target).lower() in str(value).lower()
    return False


def _rehydrate(data: dict[str, Any]) -> Postcondition:
    from app.postcondition import RequiredAction
    return Postcondition(
        goal=data.get("goal", ""),
        operation=data.get("operation", ""),
        target_url=data.get("target_url", ""),
        inputs=data.get("inputs", {}),
        required_actions=tuple(RequiredAction(**a) for a in data.get("required_actions", [])),
        claims=tuple(ClaimSpec(name=c["name"], label=c["label"],
                               relation=Relation(c["relation"]),
                               value_type=c["value_type"], container=c.get("container", ""),
                               optional=c.get("optional", False))
                     for c in data.get("claims", [])),
        absence=AbsenceMode(data.get("absence", "none")),
        coverage_anchor=data.get("coverage_anchor", ""),
        named_site=data.get("named_site", ""),
    )

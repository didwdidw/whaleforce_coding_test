"""Domain types: tiers, terminal statuses, failure classes, trace entries.

The status and failure-class sets are closed by the spec. They are enums here so an
unlisted value cannot be introduced by a typo, and so the "never present partial or
unverified as success" rule is one function rather than a convention repeated at every
call site.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class Tier(str, enum.Enum):
    """Decided before execution starts and visible in the API and the UI (S-1.3)."""

    DECLARED = "T-DECLARED"
    EXPERIMENTAL = "T-EXPERIMENTAL"
    REFUSED = "T-REFUSED"


class TerminalStatus(str, enum.Enum):
    SUCCEEDED_VERIFIED = "succeeded_verified"
    NO_RESULT_VERIFIED = "no_result_verified"
    PARTIAL = "partial"
    UNVERIFIED = "unverified"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"


#: The only two statuses that count as success. `partial` and `unverified` are absent by
#: design — every aggregation reads this set rather than deciding for itself (S-5.2).
SUCCESS_STATUSES: frozenset[TerminalStatus] = frozenset({
    TerminalStatus.SUCCEEDED_VERIFIED,
    TerminalStatus.NO_RESULT_VERIFIED,
})


def counts_as_success(status: TerminalStatus) -> bool:
    return status in SUCCESS_STATUSES


class FailureClass(str, enum.Enum):
    """Closed set. Adding a value is a spec amendment, not a code change (S-5.3)."""

    LOCATOR_NOT_FOUND = "locator_not_found"
    POSTCONDITION_UNMET = "postcondition_unmet"
    VERIFICATION_MISMATCH = "verification_mismatch"
    REQUIRED_ACTION_SKIPPED = "required_action_skipped"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    PROVIDER_QUOTA = "provider_quota"
    PROVIDER_ERROR = "provider_error"
    POLICY_REFUSED = "policy_refused"
    ROBOTS_DISALLOWED = "robots_disallowed"
    SITE_UNAVAILABLE = "site_unavailable"
    INJECTION_DETECTED = "injection_detected"
    QUEUE_FULL = "queue_full"
    SESSION_QUOTA = "session_quota"
    INTERNAL_ERROR = "internal_error"
    # Added by Amendment 7.7.
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    # Added by Amendment 17.8. A reply cut off by *our own* per-call output cap, which the
    # model's thinking tokens share. Recording it as `internal_error` blamed our code for
    # our configuration, and inflated the one rate S-5.3 says is itself a finding.
    OUTPUT_TRUNCATED = "output_truncated"


class RunState(str, enum.Enum):
    """Lifecycle position, distinct from the terminal status a run ends with."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"


class DiagnosedCause(str, enum.Enum):
    """Named causes for self-correction (S-7.6). "It threw an exception" is not a cause."""

    ELEMENT_ABSENT = "element_absent"
    NOT_INTERACTABLE = "not_interactable"
    OBSCURED_BY_OVERLAY = "obscured_by_overlay"
    NOT_YET_RENDERED = "not_yet_rendered"
    AMBIGUOUS_MATCH = "ambiguous_match"
    NAVIGATION_BLOCKED = "navigation_blocked"
    CONTENT_CHANGED = "content_changed"
    NONE = "none"


class StrategyFamily(str, enum.Enum):
    """Closed set (S-7.2). A move within one family is a retry, not a recovery."""

    F1_SEMANTIC = "F1"
    F2_TEXT_LABEL = "F2"
    F3_STRUCTURAL = "F3"
    F4_VISUAL = "F4"
    F5_ALTERNATE_ROUTE = "F5"
    F6_ALTERNATE_REPRESENTATION = "F6"


class StepKind(str, enum.Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    PRESS = "press"
    WAIT_FOR = "wait_for"
    EXTRACT = "extract"
    SNAPSHOT = "snapshot"
    POLICY_CHECK = "policy_check"
    NOTE = "note"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class TraceEntry:
    """One recorded step. The trace is the product's inspectable surface (S-11.2)."""

    seq: int
    kind: StepKind
    summary: str
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    ok: bool = True
    detail: dict[str, Any] = field(default_factory=dict)
    # Present only when this step was a repair; a retry records the same family it came
    # from, a recovery records a different one.
    diagnosed_cause: DiagnosedCause | None = None
    family_from: StrategyFamily | None = None
    family_to: StrategyFamily | None = None
    artifact_id: str | None = None

    @property
    def is_recovery(self) -> bool:
        return (self.family_from is not None
                and self.family_to is not None
                and self.family_from != self.family_to)

    @property
    def is_retry(self) -> bool:
        return (self.family_from is not None
                and self.family_from == self.family_to)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind.value,
            "summary": self.summary,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": (None if self.finished_at is None
                            else round((self.finished_at - self.started_at) * 1000)),
            "ok": self.ok,
            "detail": self.detail,
            "diagnosed_cause": self.diagnosed_cause.value if self.diagnosed_cause else None,
            "family_from": self.family_from.value if self.family_from else None,
            "family_to": self.family_to.value if self.family_to else None,
            "is_retry": self.is_retry,
            "is_recovery": self.is_recovery,
            "artifact_id": self.artifact_id,
        }


@dataclass
class BudgetUse:
    """Consumption against the run's limits, surfaced in the trace (S-6.1)."""

    steps: int = 0
    llm_calls_exploration: int = 0
    llm_calls_recovery: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    started_at: float = field(default_factory=time.time)
    # Stamped when the run ends. Without it the elapsed figure keeps counting after the run
    # is over, so a stored run reports a wall clock that grows every time it is read.
    ended_at: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        return (self.ended_at or time.time()) - self.started_at

    def to_dict(self) -> dict[str, Any]:
        from app.config import settings

        return {
            "steps": self.steps,
            "llm_calls_exploration": self.llm_calls_exploration,
            "llm_calls_recovery": self.llm_calls_recovery,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            # The cap this cost was incurred under. Output is charged at several times
            # input on this model family, so raising the cap invalidates every cost figure
            # measured below it (A17.10) — the number and the condition travel together.
            "output_cap_per_call": settings.budgets.max_output_tokens_per_call,
            "output_cap_per_run": settings.budgets.max_output_tokens_per_run,
        }


@dataclass
class Run:
    """A submitted task and everything recorded about executing it."""

    id: str
    task: str
    tier: Tier
    state: RunState = RunState.QUEUED
    session_id: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    terminal_status: TerminalStatus | None = None
    failure_class: FailureClass | None = None
    # Why the run ended as it did, in a form a user can act on. An abstention without one
    # is a product defect (A2.2), not a safe default.
    explanation: str = ""
    trace: list[TraceEntry] = field(default_factory=list)
    budget: BudgetUse = field(default_factory=BudgetUse)
    claims: list[dict[str, Any]] = field(default_factory=list)
    # Set once the planner exists; frozen and hashed at plan time (S-4.12).
    postcondition: dict[str, Any] | None = None
    postcondition_hash: str | None = None
    credential_tier: str | None = None
    browser_generation: int | None = None
    pre_executed: bool = False
    # Which of the two ways of satisfying the same postcondition actually ran. Recorded on
    # the run, not just in the trace, because the analysis report has to give a success
    # rate per path and a figure that mixes them describes neither.
    execution_path: str | None = None
    # Why this run's outcome should not be read as clean. Only ever populated for the quiet
    # outcomes — a refusal or a verified absence — where being wrong and being right look
    # identical from outside. Empty is the normal case and means the audit found nothing,
    # not that it did not run.
    suspicions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def counts_as_success(self) -> bool:
        return self.terminal_status is not None and counts_as_success(self.terminal_status)

    @property
    def effective_state(self) -> RunState:
        """The lifecycle position every surface reports (A17.7).

        A run carrying a terminal status is over, and is over on the API, in the HTML and
        in the health endpoint at the same instant. Derived rather than trusted because the
        two got out of step once already: a run refused at the door had a terminal status
        and a finish time and stayed `queued` forever, so the run page polled for a state it
        would never reach and the load test measured our queue instead of our throughput.
        """
        return RunState.DONE if self.terminal_status is not None else self.state

    def add(self, entry: TraceEntry) -> TraceEntry:
        self.trace.append(entry)
        self.budget.steps += 1
        return entry

    def next_seq(self) -> int:
        return len(self.trace) + 1

    def to_dict(self, *, include_trace: bool = True) -> dict[str, Any]:
        from app.latency import summarise  # imported here; latency reads these types

        d: dict[str, Any] = {
            "id": self.id,
            "task": self.task,
            "tier": self.tier.value,
            "state": self.effective_state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": (None if not (self.started_at and self.finished_at)
                                 else round(self.finished_at - self.started_at, 2)),
            "terminal_status": self.terminal_status.value if self.terminal_status else None,
            "failure_class": self.failure_class.value if self.failure_class else None,
            "counts_as_success": self.counts_as_success,
            "explanation": self.explanation,
            "suspicions": self.suspicions,
            "budget": self.budget.to_dict(),
            "latency": summarise(self),
            "claims": self.claims,
            "postcondition": self.postcondition,
            "postcondition_hash": self.postcondition_hash,
            "credential_tier": self.credential_tier,
            "browser_generation": self.browser_generation,
            "pre_executed": self.pre_executed,
            "execution_path": self.execution_path,
        }
        if include_trace:
            d["trace"] = [t.to_dict() for t in self.trace]
            d["retries"] = sum(1 for t in self.trace if t.is_retry)
            d["recoveries"] = sum(1 for t in self.trace if t.is_recovery)
        return d

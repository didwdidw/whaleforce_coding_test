"""Runtime configuration.

Every value is settable from the environment so the deployed system can be tuned without
a code change, and so the analysis report can record what was actually in force. Defaults
are the spec's defaults; where a default came from an M0 measurement that is noted.

Secrets are loaded from files, never from environment variables and never inlined, so they
cannot reach a trace, a log line, or a model prompt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Budgets:
    """Per-run hard limits (S-6.1, S-6.2, A7.1, A7.5, A8.12). Fail-closed on exhaustion."""

    wall_clock_seconds: float = field(default_factory=lambda: _float("BUDGET_WALL_SECONDS", 180))
    max_steps: int = field(default_factory=lambda: _int("BUDGET_MAX_STEPS", 25))
    max_llm_calls: int = field(default_factory=lambda: _int("BUDGET_MAX_LLM_CALLS", 12))
    # Exploration must not be able to consume the recovery reserve, or runs die before
    # they can demonstrate self-correction.
    exploration_calls: int = field(default_factory=lambda: _int("BUDGET_EXPLORATION_CALLS", 8))
    recovery_calls: int = field(default_factory=lambda: _int("BUDGET_RECOVERY_CALLS", 4))
    max_input_tokens_per_call: int = field(
        default_factory=lambda: _int("BUDGET_INPUT_TOKENS_PER_CALL", 8_000))
    max_input_tokens_per_run: int = field(
        default_factory=lambda: _int("BUDGET_INPUT_TOKENS_PER_RUN", 60_000))
    max_output_tokens_per_call: int = field(
        default_factory=lambda: _int("BUDGET_OUTPUT_TOKENS_PER_CALL", 1_024))
    max_output_tokens_per_run: int = field(
        default_factory=lambda: _int("BUDGET_OUTPUT_TOKENS_PER_RUN", 8_000))

    def __post_init__(self) -> None:
        if self.exploration_calls + self.recovery_calls != self.max_llm_calls:
            raise ValueError(
                f"budget split {self.exploration_calls}+{self.recovery_calls} does not sum "
                f"to max_llm_calls={self.max_llm_calls}")


@dataclass(frozen=True)
class BrowserPolicy:
    """Browser lifecycle, including the recycling that makes A9.7 tractable.

    Two weeks of continuous operation against ~1.7 GB of headroom means a 5 MB/hour leak
    exhausts the box. Chasing every leak to zero is not achievable; recycling on a
    schedule turns "prove nothing leaks" into "a leak does not accumulate". The RSS series
    is still recorded per run so a leak steeper than the recycle interval stays visible.
    """

    contexts: int = field(default_factory=lambda: _int("BROWSER_CONTEXTS", 2))
    recycle_after_runs: int = field(default_factory=lambda: _int("BROWSER_RECYCLE_RUNS", 50))
    recycle_after_seconds: float = field(
        default_factory=lambda: _float("BROWSER_RECYCLE_SECONDS", 6 * 3600))
    # A leak that would consume headroom before the next scheduled recycle recycles early.
    recycle_at_rss_mib: float = field(
        default_factory=lambda: _float("BROWSER_RECYCLE_RSS_MIB", 1_400))
    launch_timeout_seconds: float = field(
        default_factory=lambda: _float("BROWSER_LAUNCH_TIMEOUT", 60))
    # Liveness is probed out-of-band; a call that is already hung cannot report itself.
    health_probe_seconds: float = field(
        default_factory=lambda: _float("BROWSER_HEALTH_PROBE_SECONDS", 30))
    health_probe_timeout: float = field(
        default_factory=lambda: _float("BROWSER_HEALTH_PROBE_TIMEOUT", 10))
    # A container's default /dev/shm is 64 MB and Chromium dies without more (M0 §10).
    launch_args: tuple[str, ...] = ("--disable-dev-shm-usage", "--no-sandbox")


@dataclass(frozen=True)
class QueuePolicy:
    """S-11.8: concurrency 2, queue depth 2, HTTP 429 when full. No unbounded queueing."""

    concurrency: int = field(default_factory=lambda: _int("QUEUE_CONCURRENCY", 2))
    depth: int = field(default_factory=lambda: _int("QUEUE_DEPTH", 2))
    retry_after_seconds: int = field(default_factory=lambda: _int("QUEUE_RETRY_AFTER", 60))
    # S-11.12: a per-session cap on the public demo, surfaced as a designed state.
    session_run_cap: int = field(default_factory=lambda: _int("SESSION_RUN_CAP", 10))


@dataclass(frozen=True)
class ProviderPolicy:
    """Provider pacing and credentials (A9.2, A9.6, §5 of the M0 report).

    Free-tier limits measured at M0: RPM 15 / TPM 250,000 / RPD 500. The RPM ceiling is
    ours to respect proactively — discovering it from a provider 429 turns a scheduling
    decision into a run outcome, and it is a different mechanism from the user-facing
    HTTP 429 in QueuePolicy.
    """

    model_id: str = field(default_factory=lambda: _str("LLM_MODEL_ID", "gemini-3.1-flash-lite"))
    provider: str = field(default_factory=lambda: _str("LLM_PROVIDER", "gemini"))
    requests_per_minute: int = field(default_factory=lambda: _int("PROVIDER_RPM", 15))
    # Held below the measured ceiling so bursts from two concurrent runs still fit.
    rpm_safety_margin: int = field(default_factory=lambda: _int("PROVIDER_RPM_MARGIN", 2))
    free_key_path: Path = REPO_ROOT / "api_keys" / "Free_tier_agent_API_Key"
    paid_key_path: Path = REPO_ROOT / "api_keys" / "Billing_agent_API_Key"

    @property
    def effective_rpm(self) -> int:
        return max(1, self.requests_per_minute - self.rpm_safety_margin)


@dataclass(frozen=True)
class Settings:
    budgets: Budgets = field(default_factory=Budgets)
    browser: BrowserPolicy = field(default_factory=BrowserPolicy)
    queue: QueuePolicy = field(default_factory=QueuePolicy)
    provider: ProviderPolicy = field(default_factory=ProviderPolicy)

    data_dir: Path = field(default_factory=lambda: Path(_str("DATA_DIR", "/tmp/task1-data")))
    fixture_base_url: str = field(
        default_factory=lambda: _str("FIXTURE_BASE_URL", "http://127.0.0.1:8801"))
    user_agent: str = field(default_factory=lambda: _str(
        "HTTP_USER_AGENT",
        "WhaleforceCodingTest-Task1/0.1 (contact: didwdidw0309@gmail.com)"))
    # Artifacts expire as a recorded state, never as a dangling reference (A9.7.2).
    artifact_retention_days: int = field(
        default_factory=lambda: _int("ARTIFACT_RETENTION_DAYS", 14))
    artifact_store_max_mib: int = field(
        default_factory=lambda: _int("ARTIFACT_STORE_MAX_MIB", 4_000))
    # The egress guard blocks private address space; the fixture must therefore be reached
    # over a public hostname, with no allow-list hole (S-2.8). Relaxed only for local dev.
    allow_private_egress: bool = field(
        default_factory=lambda: _bool("ALLOW_PRIVATE_EGRESS", False))

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "runs.sqlite3"


settings = Settings()

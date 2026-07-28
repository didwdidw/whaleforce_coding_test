"""The only place a provider-specific call exists (S-11.14).

Everything that makes a model call *bounded* lives here rather than at the call sites,
because a budget enforced in four places is a budget with three ways to be forgotten:

- the per-call input cap (A7.1) — a call over the cap is **not sent**, it fails closed;
- the per-run input and output budgets (A7.5, A8.12) — output is the dominant cost at these
  prices, so it is capped per call *and* cumulatively;
- provider pacing against the measured RPM ceiling, so a scheduling decision never becomes
  a run outcome;
- which credential tier paid for the call (A8.9), because A7.9's disclosure — free-tier
  content is used by the provider to improve its products, paid-tier content is not — is
  only accurate if the tier is recorded rather than assumed.

Keys are read from files and never from the environment, so a stray environment dump cannot
put one in a trace, a log line or a prompt record.
"""

from __future__ import annotations

import enum
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import DEPLOYED_CEILING_SHARE, settings
from app.models import FailureClass

log = logging.getLogger(__name__)

#: Model ids that must never be pinned (S-11.15): they move under us, and a moving model
#: makes every recorded score unreproducible.
FORBIDDEN_MARKERS = ("latest", "preview", "exp", "experimental")


def looks_like_moving_alias(model_id: str) -> bool:
    """Whether an id names something that can change under us.

    Split out from the startup check so both halves are testable: refusing a moving alias
    needs no provider, but proving the *pinned* id is accepted otherwise costs a live call,
    and a rule that only ever gets asked about ids it rejects is one nobody can tell from a
    rule that rejects everything.
    """
    return any(marker in model_id.lower() for marker in FORBIDDEN_MARKERS)


class CredentialTier(str, enum.Enum):
    FREE = "free"
    PAID = "paid"
    NONE = "none"


class CredentialPolicy(str, enum.Enum):
    """Which keys a run may use, decided by what the run is for (A8.8, A9.6)."""

    #: The public demo. Free tier only — a visitor must never spend billed quota, and
    #: exhaustion is an honest `blocked / provider_quota` rather than a silent upgrade.
    PUBLIC_DEMO = "public_demo"
    #: Development. Free first, automatic fallback to paid.
    DEVELOPMENT = "development"
    #: Validation and test splits. Paid unconditionally (A9.6) — a held-out split cannot be
    #: re-run, so it must not be able to die of free-tier exhaustion halfway.
    SCORED = "scored"


class ProviderError(Exception):
    failure_class = FailureClass.PROVIDER_ERROR

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class ProviderQuotaExhausted(ProviderError):
    failure_class = FailureClass.PROVIDER_QUOTA


class ContextBudgetExceeded(ProviderError):
    """The assembled context is over the per-call cap. The call is not sent (A7.1)."""

    failure_class = FailureClass.CONTEXT_BUDGET_EXCEEDED


class TokenBudgetExhausted(ProviderError):
    failure_class = FailureClass.TOKEN_BUDGET_EXHAUSTED


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "thought_tokens": self.thought_tokens, "usd": round(self.usd, 6)}


@dataclass
class Completion:
    text: str
    usage: Usage
    model: str
    credential_tier: CredentialTier
    cached: bool
    seconds: float
    finish_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "credential_tier": self.credential_tier.value,
                "cached": self.cached, "seconds": round(self.seconds, 3),
                "finish_reason": self.finish_reason, **self.usage.to_dict()}


@dataclass
class RunBudget:
    """One run's cumulative allowance. Held by the run, enforced here."""

    input_tokens: int = 0
    output_tokens: int = 0
    exploration_calls: int = 0
    recovery_calls: int = 0
    usd: float = 0.0

    def check_calls(self, purpose: str) -> None:
        b = settings.budgets
        if purpose == "recovery":
            if self.recovery_calls >= b.recovery_calls:
                raise ProviderError(
                    f"The recovery call budget ({b.recovery_calls}) is exhausted.",
                    detail={"budget": "recovery_calls"})
        elif self.exploration_calls >= b.exploration_calls:
            # Exploration must not be able to eat the recovery reserve, or a run dies
            # before it can demonstrate the self-correction it is being graded on.
            raise ProviderError(
                f"The exploration call budget ({b.exploration_calls}) is exhausted. The "
                f"recovery reserve is held separately and is not available to it.",
                detail={"budget": "exploration_calls"})

    def check_tokens(self, prospective_input: int) -> None:
        b = settings.budgets
        if prospective_input > b.max_input_tokens_per_call:
            raise ContextBudgetExceeded(
                f"The assembled context is {prospective_input} tokens against a per-call "
                f"cap of {b.max_input_tokens_per_call}. It was not sent: reducing further "
                f"or failing closed are the only options (A7.1).",
                detail={"tokens": prospective_input,
                        "cap": b.max_input_tokens_per_call})
        if self.input_tokens + prospective_input > b.max_input_tokens_per_run:
            raise TokenBudgetExhausted(
                f"This run has used {self.input_tokens} of its "
                f"{b.max_input_tokens_per_run} input-token budget; the next call would "
                f"exceed it. Budgets are fail-closed.",
                detail={"used": self.input_tokens, "cap": b.max_input_tokens_per_run})
        if self.output_tokens >= b.max_output_tokens_per_run:
            raise TokenBudgetExhausted(
                f"This run has used its {b.max_output_tokens_per_run} output-token budget. "
                f"Output is the dominant cost at these prices (A8.12).",
                detail={"used": self.output_tokens,
                        "cap": b.max_output_tokens_per_run})

    def record(self, usage: Usage, purpose: str) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.usd += usage.usd
        if purpose == "recovery":
            self.recovery_calls += 1
        else:
            self.exploration_calls += 1

    def to_dict(self) -> dict[str, Any]:
        b = settings.budgets
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
            "exploration_calls": f"{self.exploration_calls}/{b.exploration_calls}",
            "recovery_calls": f"{self.recovery_calls}/{b.recovery_calls}",
        }


def _read_key(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


@dataclass
class Provider:
    """Gemini adapter. Constructing it does not call anything; `validate_or_die` does."""

    model_id: str = field(default_factory=lambda: settings.provider.model_id)
    policy: CredentialPolicy = field(
        default_factory=lambda: CredentialPolicy(settings.provider.credential_policy))
    cache_enabled: bool = field(default_factory=lambda: settings.provider.cache_enabled)
    _cache: dict[str, Completion] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_call: float = 0.0
    #: Tier -> the moment it may be tried again. A rate limit is a statement about a
    #: window, not about the key: RPM resets in a minute, and marking a tier dead for the
    #: life of the process meant one burst disabled the model path until the next deploy.
    _quota_exhausted: dict[CredentialTier, float] = field(default_factory=dict)
    #: Where spend is counted. Optional so the adapter still works without a store (the
    #: model comparison runs outside the app), but the deployed path always has one.
    ledger: Any = None

    # ---- credentials -----------------------------------------------------------

    def key_for(self, tier: CredentialTier) -> str | None:
        p = settings.provider
        free = tier is CredentialTier.FREE
        candidates = (
            p.key_dir / (p.free_key_name if free else p.paid_key_name),
            p.repo_key_dir / (p.repo_free_key_name if free else p.repo_paid_key_name),
        )
        for path in candidates:
            key = _read_key(path)
            if key:
                return key
        return None

    def credential_state(self) -> dict[str, Any]:
        """What `/healthz` is allowed to say about credentials: whether one exists and
        which tier it is. Never the value, a prefix, or a length — a length is a fact about
        the secret, and this endpoint is public.
        """
        present = [t.value for t in (CredentialTier.FREE, CredentialTier.PAID)
                   if self.key_for(t) is not None]
        usable = [t.value for t in self.available_tiers() if self.key_for(t) is not None]
        return {
            "configured": bool(usable),
            "tiers_present": present,
            "tiers_usable_under_policy": usable,
            "policy": self.policy.value,
            "search_path": str(settings.provider.key_dir),
        }

    def available_tiers(self) -> list[CredentialTier]:
        """The tiers this run may use, in order, given what it is for."""
        if self.policy is CredentialPolicy.SCORED:
            return [CredentialTier.PAID]
        if self.policy is CredentialPolicy.PUBLIC_DEMO:
            # No fallback. A visitor's run must not spend billed quota, and exhaustion is
            # reported rather than papered over.
            return [CredentialTier.FREE]
        return [CredentialTier.FREE, CredentialTier.PAID]

    def configured(self) -> bool:
        return any(self.key_for(t) for t in self.available_tiers())

    # ---- startup ---------------------------------------------------------------

    def validate_or_die(self) -> dict[str, Any]:
        """A live minimal call, not a `models.list()` lookup (A9.3).

        Both models this project lost were present in the list response and failed only on
        use. A list-based check passes and then fails at the first real call, which surfaces
        as a mid-run `provider_error` instead of a refusal to start.
        """
        if looks_like_moving_alias(self.model_id):
            raise SystemExit(
                f"REFUSING TO START: model id '{self.model_id}' looks like a moving alias "
                f"or a preview model. A pinned stable id is required (S-11.15) — a model "
                f"that changes under us makes every recorded score unreproducible.")
        completion = self.complete('Reply with exactly {"ok": true}',
                                   budget=RunBudget(), purpose="startup",
                                   max_output_tokens=64)
        # An empty body with a clean finish is still a live model; what proves the call
        # actually happened is that the provider counted our prompt.
        if completion.usage.input_tokens <= 0:
            raise SystemExit(
                f"REFUSING TO START: the pinned model '{self.model_id}' answered without "
                f"reporting any token usage, so it is not possible to tell whether the "
                f"call reached it. S-11.16 forbids a silent fallback to another model.")
        return {"model": self.model_id, "reachable": True,
                "credential_tier": completion.credential_tier.value,
                "finish_reason": completion.finish_reason,
                "usage": completion.usage.to_dict(),
                "reply": completion.text.strip()[:60]}

    # ---- the call --------------------------------------------------------------

    def _pace(self) -> float:
        """Respect the measured RPM ceiling proactively. Discovering it from a provider 429
        turns a scheduling decision into a run outcome."""
        interval = 60.0 / max(1, settings.provider.effective_rpm)
        with self._lock:
            wait = max(0.0, self._last_call + interval - time.time())
            if wait:
                time.sleep(wait)
            self._last_call = time.time()
        return wait

    def complete(self, prompt: str, *, budget: RunBudget, purpose: str,
                 max_output_tokens: int | None = None) -> Completion:
        if purpose != "startup":
            budget.check_calls(purpose)
        estimated = estimate_tokens(prompt)
        if purpose != "startup":
            budget.check_tokens(estimated)

        cache_key = hashlib.sha256(
            f"{self.model_id}|{max_output_tokens}|{prompt}".encode()).hexdigest()
        if self.cache_enabled and cache_key in self._cache:
            # Dev-only (A8.13). Every reported performance or cost figure comes from
            # uncached runs; a cached hit is marked so it can never be counted as one.
            hit = self._cache[cache_key]
            return Completion(hit.text, Usage(), hit.model, hit.credential_tier,
                              cached=True, seconds=0.0, finish_reason=hit.finish_reason)

        self._check_spend()

        last_error: ProviderError | None = None
        cooling: list[str] = []
        for tier in self.available_tiers():
            resume_at = self._quota_exhausted.get(tier, 0.0)
            if resume_at > time.time():
                cooling.append(f"{tier.value} (retryable in "
                               f"{round(resume_at - time.time())}s)")
                continue
            key = self.key_for(tier)
            if key is None:
                continue
            try:
                completion = self._call(prompt, key, tier, max_output_tokens)
            except ProviderQuotaExhausted as exc:
                self._quota_exhausted[tier] = (time.time()
                                               + settings.provider.quota_cooldown_seconds)
                last_error = exc
                log.warning("provider quota exhausted on the %s tier", tier.value)
                continue
            if purpose != "startup":
                budget.record(completion.usage, purpose)
            self._record_spend(completion)
            if self.cache_enabled:
                self._cache[cache_key] = completion
            return completion

        if last_error is not None:
            if self.policy is CredentialPolicy.PUBLIC_DEMO:
                raise ProviderQuotaExhausted(
                    "The free-tier provider quota for the public demo is exhausted. The "
                    "demo does not fall back to billed credentials, so this run stops here "
                    "rather than spending them.", detail=last_error.detail)
            raise last_error
        if cooling:
            # Every usable tier is inside a quota cooldown. This is a quota condition and
            # has to be named as one: reported as `provider_error` it read as a broken
            # deployment, and it inflated the class S-5.3 treats as a finding in itself.
            raise ProviderQuotaExhausted(
                f"Every credential tier available under the {self.policy.value} policy is "
                f"rate-limited right now: {', '.join(cooling)}. This is a quota window, not "
                f"a fault; the tier is tried again when it expires.",
                detail={"cooling": cooling})
        raise ProviderError(
            f"No usable credential for the {self.policy.value} policy. Expected a key file "
            f"in {settings.provider.key_dir} or {settings.provider.repo_key_dir}.")

    def _check_spend(self) -> None:
        """Refuse before the call, not after. A ceiling checked afterwards is a report."""
        if self.ledger is None:
            return
        spend = self.ledger.spend()
        p = settings.provider
        if spend["cumulative_usd"] >= p.spend_ceiling_usd:
            raise ProviderQuotaExhausted(
                f"The cumulative provider spend ceiling of ${p.spend_ceiling_usd:.2f} has "
                f"been reached (${spend['cumulative_usd']:.4f} spent over "
                f"{spend['cumulative_calls']} calls). This is A8.10's self-approval limit "
                f"enforced at runtime rather than remembered; raising it is a decision, not "
                f"a configuration change.",
                detail={"ceiling": "cumulative", **spend})
        if spend["today_usd"] >= p.spend_ceiling_usd_per_day:
            raise ProviderQuotaExhausted(
                f"Today's provider spend ceiling of ${p.spend_ceiling_usd_per_day:.2f} has "
                f"been reached (${spend['today_usd']:.4f} over {spend['today_calls']} "
                f"calls). The run stops here rather than continuing to spend.",
                detail={"ceiling": "daily", **spend})

    def _record_spend(self, completion: Completion) -> None:
        if self.ledger is None or completion.cached:
            return
        self.ledger.record_spend(completion.credential_tier.value, completion.usage.usd,
                                 completion.usage.input_tokens,
                                 completion.usage.output_tokens)

    def spend_state(self) -> dict[str, Any]:
        p = settings.provider
        spend = self.ledger.spend() if self.ledger is not None else {}
        return {
            **spend,
            "ceiling_usd": p.spend_ceiling_usd,
            "ceiling_usd_per_day": p.spend_ceiling_usd_per_day,
            # A22.4: the promise is a system number, and the two processes that divide it
            # cannot see each other's ledger. A reader who has to add up two services to
            # find the number we promised is not being shown the promise.
            "credential_policy": p.credential_policy,
            "share_of_system": p.ceiling_share_of_system,
            "system_ceiling_usd_per_day": p.system_spend_ceiling_usd_per_day,
            "system_split": dict(DEPLOYED_CEILING_SHARE),
            "enforced": self.ledger is not None,
            "note": ("Checked before every call. A8.10's ceiling was a number held in "
                     "someone's head until this existed; exceeding it is a refusal, not a "
                     "warning. This process's own spend is what appears above; the system "
                     "total is the sum across the split, and no process can read the "
                     "other's ledger."),
        }

    def _call(self, prompt: str, key: str, tier: CredentialTier,
              max_output_tokens: int | None) -> Completion:
        from google import genai
        from google.genai import types

        cap = max_output_tokens or settings.budgets.max_output_tokens_per_call
        config = types.GenerateContentConfig(
            max_output_tokens=cap,
            temperature=settings.provider.temperature,
            response_mime_type="application/json"
            if settings.provider.json_mode else None,
        )
        if settings.provider.thinking_level:
            # Output is billed including thinking tokens, so it is bounded rather than
            # left at the model's default (A8.12).
            config.thinking_config = types.ThinkingConfig(
                thinking_level=settings.provider.thinking_level)

        self._pace()
        started = time.time()
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=self.model_id, contents=prompt, config=config)
        except Exception as exc:  # noqa: BLE001 - classified, never swallowed
            raise _classify(exc) from exc

        meta = getattr(response, "usage_metadata", None)
        usage = Usage(
            input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
            output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
            thought_tokens=getattr(meta, "thoughts_token_count", 0) or 0)
        usage.output_tokens += usage.thought_tokens
        usage.usd = self.cost(usage)
        finish = None
        if getattr(response, "candidates", None):
            finish = str(getattr(response.candidates[0], "finish_reason", "") or "")
        return Completion(response.text or "", usage, self.model_id, tier,
                          cached=False, seconds=time.time() - started,
                          finish_reason=finish)

    def cost(self, usage: Usage) -> float:
        """Prices come from configuration, not from a constant in the code (A7.6)."""
        pin, pout = settings.provider.prices_usd_per_1m
        return (usage.input_tokens * pin + usage.output_tokens * pout) / 1_000_000

    def describe(self) -> dict[str, Any]:
        return {
            "model": self.model_id,
            "credential_policy": self.policy.value,
            "tiers_available": [t.value for t in self.available_tiers()],
            "configured": self.configured(),
            "prices_usd_per_1m": {"input": settings.provider.prices_usd_per_1m[0],
                                  "output": settings.provider.prices_usd_per_1m[1]},
            # Output is the dominant term at these prices, so the cap is a cost lever and
            # not a detail: a cost range measured under one cap does not describe another.
            "output_cap_per_call": settings.budgets.max_output_tokens_per_call,
            "output_cap_per_run": settings.budgets.max_output_tokens_per_run,
            "effective_rpm": settings.provider.effective_rpm,
            "cache_enabled": self.cache_enabled,
            "quota_cooling_tiers": {t.value: round(max(0.0, until - time.time()))
                                    for t, until in self._quota_exhausted.items()
                                    if until > time.time()},
            "note": ("Free-tier content is used by the provider to improve its products; "
                     "paid-tier content is not. The tier is recorded per run so that "
                     "disclosure stays accurate (A7.9, A8.9)."),
        }


def estimate_tokens(text: str) -> int:
    """A local upper-ish estimate, used to decide whether a call may be sent at all.

    It has to be local: asking the provider how big the prompt is means sending it, which
    is the thing the cap exists to prevent. ~4 characters per token is the usual English
    ratio; JSON-heavy reduced views run denser, so this errs high on purpose.
    """
    return max(1, len(text) // 3)


def _classify(exc: Exception) -> ProviderError:
    """Provider failures split into quota and everything else, because they mean different
    things to a run: one is a resource limit, the other is a fault."""
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    quota_markers = ("resource_exhausted", "429", "quota", "rate limit", "rate_limit")
    if any(m in lowered for m in quota_markers):
        return ProviderQuotaExhausted(text, detail={"provider_error": text[:400]})
    return ProviderError(text, detail={"provider_error": text[:400]})

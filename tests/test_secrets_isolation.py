"""The key directory is outside the artifact store, and nothing in the store reaches it.

`/data` is the root the evidence store serves from over HTTP. A secret living in that tree
would be one path-handling mistake away from being handed out, so the keys live somewhere
else entirely. These tests are what keeps that from being a fact about today's paths: the
store must not enumerate the key directory, must not serve anything from it, and retention
must not touch it — and the health endpoint must say whether a key exists without saying
anything about the key.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.config import settings
from app.provider import CredentialPolicy, CredentialTier, Provider
from app.store import Store

SECRET = "AIzaSy-not-a-real-key-0123456789abcdefg"


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(tmp_path / "runs.sqlite3", tmp_path / "artifacts")


@pytest.fixture()
def key_dir(tmp_path, monkeypatch) -> pathlib.Path:
    """A key directory that is deliberately a sibling of the data directory, never under
    it — the same relationship `/etc/wf` has to `/data` in the deployment."""
    directory = tmp_path / "etc-wf"
    directory.mkdir()
    (directory / "gemini_free_tier").write_text(SECRET, encoding="utf-8")
    object.__setattr__(settings.provider, "key_dir", directory)
    yield directory
    object.__setattr__(settings.provider, "key_dir", pathlib.Path("/etc/wf"))


# --- the structural property ------------------------------------------------------

def test_the_key_directory_is_not_inside_the_data_directory():
    """The deployment's actual paths, asserted rather than assumed."""
    data = settings.data_dir.resolve()
    keys = settings.provider.key_dir.resolve()
    assert keys != data
    assert data not in keys.parents, (
        f"the key directory {keys} sits inside the artifact store root {data}; the store "
        f"serves that tree over HTTP")


def test_the_store_only_ever_reads_from_its_own_directory(store, key_dir):
    """A row pointing outside the store is refused, not read.

    The path comes out of the database and the store hands its contents to anyone over
    HTTP. Without the containment check, one bad row is the difference between serving
    evidence and serving whatever the row points at.
    """
    ref = store.put_artifact("run_x", "dom:test", b"<html>evidence</html>",
                             source_url="https://example.com/", media_type="text/html")
    store._conn.execute("UPDATE artifacts SET path = ? WHERE id = ?",
                        (str(key_dir / "gemini_free_tier"), ref.id))
    store._conn.commit()

    assert store.read_artifact(ref.id) is None
    assert store.contains(key_dir / "gemini_free_tier") is False
    assert store.contains(store.artifact_dir / "anything.bin") is True


def test_a_traversal_path_cannot_escape_the_store(store, key_dir):
    ref = store.put_artifact("run_x", "dom:test", b"x")
    escape = store.artifact_dir / ".." / ".." / "etc-wf" / "gemini_free_tier"
    store._conn.execute("UPDATE artifacts SET path = ? WHERE id = ?", (str(escape), ref.id))
    store._conn.commit()
    assert store.read_artifact(ref.id) is None


def test_the_store_never_enumerates_the_key_directory(store, key_dir):
    """Nothing the store lists comes from anywhere but its own directory."""
    store.put_artifact("run_x", "dom:test", b"x")
    listed = [pathlib.Path(row["path"]) for row in
              store._conn.execute("SELECT path FROM artifacts WHERE path IS NOT NULL")]
    assert listed and all(store.contains(p) for p in listed)
    assert (key_dir / "gemini_free_tier").exists()      # still there, simply not ours


def test_retention_never_touches_anything_outside_the_store(store, key_dir):
    """Retention deletes bytes. It must not be able to delete a key."""
    ref = store.put_artifact("run_x", "dom:test", b"x")
    store._conn.execute("UPDATE artifacts SET path = ? WHERE id = ?",
                        (str(key_dir / "gemini_free_tier"), ref.id))
    store._conn.commit()

    store.enforce_retention(retention_days=0)

    assert (key_dir / "gemini_free_tier").read_text(encoding="utf-8") == SECRET


# --- what the health endpoint may say ---------------------------------------------

def test_health_reports_presence_and_tier_and_nothing_else(key_dir):
    state = Provider(policy=CredentialPolicy.DEVELOPMENT).credential_state()
    assert state["configured"] is True
    assert "free" in state["tiers_present"]

    body = json.dumps(state)
    assert SECRET not in body
    assert SECRET[:8] not in body                       # no prefix
    # No length either — that is a fact about the secret. Checked against the reported
    # values rather than by scanning the whole document: a temp path can contain the
    # number by coincidence, and a test that fails on a coincidence teaches nothing.
    assert len(SECRET) not in [v for v in state.values() if isinstance(v, int)]
    assert str(len(SECRET)) not in json.dumps(
        {k: v for k, v in state.items() if k != "search_path"})


def test_the_key_value_never_reaches_a_repr(key_dir):
    """A provider that prints its key ends up printing it into a trace."""
    provider = Provider(policy=CredentialPolicy.DEVELOPMENT)
    provider.key_for(CredentialTier.FREE)
    assert SECRET not in repr(provider)
    assert SECRET not in json.dumps(provider.describe())


# --- degradation without a credential ---------------------------------------------

def test_no_credential_is_a_degraded_deployment_not_a_dead_one(tmp_path, monkeypatch):
    """A service that refuses to boot without a key is a service nobody can demonstrate.

    Everything deterministic — the fixture operations, the verifier, the evidence store —
    works with no model at all. What must not happen is looking healthy and then failing
    obscurely at the first planned run.
    """
    empty = tmp_path / "no-keys"
    empty.mkdir()
    object.__setattr__(settings.provider, "key_dir", empty)
    original_repo = settings.provider.repo_key_dir
    object.__setattr__(settings.provider, "repo_key_dir", empty)
    try:
        provider = Provider(policy=CredentialPolicy.PUBLIC_DEMO)
        assert provider.configured() is False
        state = provider.credential_state()
        assert state["configured"] is False
        assert state["tiers_present"] == []
    finally:
        object.__setattr__(settings.provider, "key_dir", pathlib.Path("/etc/wf"))
        object.__setattr__(settings.provider, "repo_key_dir", original_repo)


def test_the_public_demo_cannot_reach_a_paid_key_even_when_one_is_present(key_dir):
    """The control that survives the paid key arriving on the machine.

    Once a paid credential exists on the host, "the key is not there" stops protecting
    anything, so the policy has to. A public-demo provider lists no paid tier as usable
    regardless of what is on disk.
    """
    (key_dir / "gemini_paid_tier").write_text("AIzaSy-paid-key-not-real", encoding="utf-8")
    demo = Provider(policy=CredentialPolicy.PUBLIC_DEMO)
    state = demo.credential_state()

    assert "paid" in state["tiers_present"]
    assert state["tiers_usable_under_policy"] == ["free"]
    assert demo.available_tiers() == [CredentialTier.FREE]


# --- A27: the switchover is a policy value, not a reuse of an existing one --------

def test_the_funded_public_demo_may_fall_back_and_has_an_allowance_of_its_own(key_dir):
    """A15.1/A27.1. Free stays first: the daily free allowance is spent before a billed
    call is made, and the paid key is what stops a rate limit becoming a run outcome."""
    (key_dir / "gemini_paid_tier").write_text("AIzaSy-paid-key-not-real", encoding="utf-8")
    funded = Provider(policy=CredentialPolicy.PUBLIC_DEMO_FUNDED)
    cumulative, daily = funded.ceilings()

    assert funded.available_tiers() == [CredentialTier.FREE, CredentialTier.PAID]
    assert funded.credential_state()["tiers_usable_under_policy"] == ["free", "paid"]
    assert funded.credential_state()["policy"] == "public_demo_funded"
    assert cumulative == pytest.approx(2.00)
    assert daily == pytest.approx(0.50)


def test_the_pre_switchover_policy_is_untouched_by_the_switchover(key_dir):
    """The new value is only honest if the old one still means what it meant. Both remain
    reachable, and a deployment that has not switched behaves exactly as before."""
    (key_dir / "gemini_paid_tier").write_text("AIzaSy-paid-key-not-real", encoding="utf-8")
    demo = Provider(policy=CredentialPolicy.PUBLIC_DEMO)
    cumulative, daily = demo.ceilings()

    assert demo.available_tiers() == [CredentialTier.FREE]
    assert cumulative == 0.0
    assert daily == pytest.approx(0.50)
    assert demo.spend_state()["billed_spend_authorised"] is False


def test_a_tier_list_that_can_spend_under_an_allowance_of_zero_refuses_before_the_call(
        key_dir, store, monkeypatch):
    """The second control, and it is worth being precise about which one does the work.

    Under `public_demo` the paid tier is not in the tier list at all, so the zero allowance
    never gets asked — the test above is what protects that deployment. This branch covers
    the slip the switchover makes possible: a policy that *may* reach the paid key while its
    allowance is missing or zero. Reached here by removing the allowance rather than by
    patching the tier list, because that is the mistake with a plausible way of happening.
    """
    (key_dir / "gemini_paid_tier").write_text("AIzaSy-paid-key-not-real", encoding="utf-8")
    from app import config
    from app.provider import ProviderQuotaExhausted

    funded = Provider(policy=CredentialPolicy.PUBLIC_DEMO_FUNDED, ledger=store)
    funded._check_spend()  # with its declared allowance, nothing to refuse

    monkeypatch.setitem(config.CUMULATIVE_CEILING_USD, "public_demo_funded", 0.0)
    with pytest.raises(ProviderQuotaExhausted) as raised:
        funded._check_spend()
    assert "no authorised cumulative spend" in str(raised.value)


def test_the_credential_policy_does_not_move_the_ssrf_guard():
    """The one coupling worth being sure about. The guard reads APP_ENV and
    ALLOW_PRIVATE_EGRESS; which credentials a run may use says nothing about where it may
    connect, and switching the money must not quietly switch the network policy."""
    import dataclasses

    guard = {policy: dataclasses.replace(
        settings, provider=dataclasses.replace(settings.provider,
                                               credential_policy=policy)).egress_guard_state()
        for policy in ("public_demo", "public_demo_funded", "scored")}

    assert len({json.dumps(g, sort_keys=True) for g in guard.values()}) == 1
    assert guard["public_demo_funded"]["ssrf_guard_enabled"] is True

from yoke_core.domain.sessions_lifecycle_identity import trusted_native_thread_id
from yoke_harness.hooks.identity_relay import client_native_thread_id


def test_codex_native_thread_rejects_cross_chat_delegation(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "sender")

    assert client_native_thread_id("codex-desktop", "destination") is None


def test_native_thread_identity_accepts_first_observation():
    assert trusted_native_thread_id("codex", "session", None, "native") == "native"


def test_native_thread_identity_ignores_uncorroborated_replacement():
    assert (
        trusted_native_thread_id("codex", "session", "stored", "delegated")
        == "stored"
    )


def test_native_thread_identity_heals_with_owning_codex_thread():
    assert (
        trusted_native_thread_id("codex", "session", "delegated", "session")
        == "session"
    )


def test_non_codex_native_thread_identity_accepts_replacement():
    assert (
        trusted_native_thread_id("claude-code", "session", "stored", "current")
        == "current"
    )

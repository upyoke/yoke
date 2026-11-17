"""Harness lifecycle registration uses target-aware service-client paths."""

from __future__ import annotations

from yoke_core.hooks import session_lifecycle_client
from yoke_core.hooks import session_dispatch
from yoke_contracts.session_model_facts import SessionModelFacts



def _pin_local_transport(monkeypatch) -> None:
    """Pin the branch these tests are about: the service-client subprocess.

    Two other branches reach lifecycle work first, and each is chosen from
    the running machine's own connection — the relay-owned registration skip
    on an https machine, and in-process dispatch on a machine that owns its
    universe. Left ambient, either one answers from the operator's config
    rather than from the code under test, so the assertions turn on where
    the suite happens to run.
    """
    monkeypatch.setattr(
        session_lifecycle_client,
        "_relay_owns_registration",
        lambda: False,
    )
    monkeypatch.setattr(
        session_lifecycle_client,
        "_local_authority_active",
        lambda: False,
    )
    monkeypatch.setattr(
        session_lifecycle_client,
        "_project_id_for_root",
        lambda _root: 1,
    )


def test_codex_registration_preserves_target_scope_and_native_thread(monkeypatch):
    _pin_local_transport(monkeypatch)
    monkeypatch.delenv("YOKE_EXECUTOR", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-42")
    calls = []
    def register(*args, **kwargs):
        calls.append((args, kwargs))
        return "registered"
    monkeypatch.setattr("yoke_core.hooks.registration_in_process._register_in_process", register)
    facts = SessionModelFacts(requested_model="gpt-test")
    assert session_dispatch._register_codex("/target", "session", facts, "codex-desktop") == "registered"
    args, kwargs = calls[0]
    assert args == ("session", "codex", "openai", facts, "/target", "codex-desktop")
    assert kwargs["project_id"] == 1
    assert kwargs["machine_scope"] is False
    assert kwargs["native_thread_id"] == "thread-42"


def test_universal_registration_preserves_target_and_scope(monkeypatch):
    _pin_local_transport(monkeypatch)
    calls = []
    def register(*args, **kwargs):
        calls.append((args, kwargs))
        return "exists"
    monkeypatch.setattr("yoke_core.hooks.registration_in_process._register_in_process", register)
    facts = SessionModelFacts(requested_model="model-test")
    assert session_lifecycle_client.register_harness_session(
        root="/target", session_id="session", executor="claude-code",
        provider="anthropic", model_facts=facts, entrypoint="claude-desktop",
    ) == "exists"
    args, kwargs = calls[0]
    assert args == ("session", "claude-code", "anthropic", facts, "/target", "claude-desktop")
    assert kwargs["project_id"] == 1
    assert kwargs["machine_scope"] is False


def test_codex_touch_uses_target_service_client_path(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_touch(*args):  # noqa: ANN001
        calls.append(args)
        return 0

    _pin_local_transport(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.hooks.target.target_service_client_path",
        lambda root: "/Users/x/yoke/runtime/api/service_client.py",
    )
    monkeypatch.setattr(
        "yoke_core.hooks.service_client.touch_session",
        fake_touch,
    )

    assert session_dispatch._touch("/Users/x/externalwebapp", "sid-codex") == 0
    assert calls == [
        (
            "/Users/x/yoke/runtime/api/service_client.py",
            "/Users/x/externalwebapp",
            "sid-codex",
        )
    ]


def test_universal_touch_uses_target_service_client_path(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_touch(*args):  # noqa: ANN001
        calls.append(args)
        return 0

    _pin_local_transport(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.hooks.target.target_service_client_path",
        lambda root: "/Users/x/yoke/runtime/api/service_client.py",
    )
    monkeypatch.setattr(
        "yoke_core.hooks.service_client.touch_session",
        fake_touch,
    )

    assert (
        session_lifecycle_client.touch_harness_session(
            "/Users/x/externalwebapp",
            "sid-any",
        )
        == 0
    )
    assert calls == [
        (
            "/Users/x/yoke/runtime/api/service_client.py",
            "/Users/x/externalwebapp",
            "sid-any",
        )
    ]


def test_lifecycle_recovery_command_uses_target_service_client_path(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.hooks.target.target_service_client_path",
        lambda root: "/Users/x/yoke/runtime/api/service_client.py",
    )

    command = session_lifecycle_client.session_begin_recovery_command(
        root="/Users/x/externalwebapp",
        session_id="sid-codex",
        executor="codex",
        provider="openai",
        requested_model="gpt-5.5",
        entrypoint="codex-desktop",
    )

    assert command.startswith(
        "python3 /Users/x/yoke/runtime/api/service_client.py session-begin "
    )
    assert "--workspace /Users/x/externalwebapp" in command
    assert "--entrypoint codex-desktop" in command


def test_generic_hook_registration_uses_universal_lifecycle_client(
    monkeypatch,
) -> None:
    from yoke_core.hooks import registration as hook_runner_register

    calls: list[dict] = []

    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)

    def fake_register(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        return ""

    monkeypatch.setattr(
        hook_runner_register,
        "resolve_hook_script_dir",
        lambda: "/Users/x/yoke/.agents/skills/yoke/scripts",
    )
    monkeypatch.setattr(
        hook_runner_register,
        "resolve_target_root",
        lambda _script_dir: "/Users/x/externalwebapp",
    )
    monkeypatch.setattr(hook_runner_register, "is_yoke_target", lambda *_args: True)
    monkeypatch.setattr(
        "yoke_core.hooks.helpers.resolve_yoke_db",
        lambda _script_dir: "",
    )
    monkeypatch.setattr(
        "yoke_core.hooks.helpers.detect_executor",
        lambda: "claude",
    )
    monkeypatch.setattr(
        "yoke_core.hooks.helpers.detect_provider",
        lambda _executor: "anthropic",
    )
    monkeypatch.setattr(
        "yoke_core.hooks.helpers.detect_entrypoint",
        lambda: "claude-desktop",
    )
    monkeypatch.setattr(
        hook_runner_register,
        "enrich_local_observed_facts",
        lambda *_args, **_kwargs: (
            "0.1.0",
            "00000000-0000-4000-8000-000000000123",
        ),
    )
    monkeypatch.setattr(hook_runner_register, "register_harness_session", fake_register)

    err, executor, provider, facts, entrypoint = (
        hook_runner_register._register_from_hook(
            '{"requested_model":"claude-opus-4-8[1m]"}',
            "sid-claude",
        )
    )

    assert err == ""
    assert (executor, provider, entrypoint) == (
        "claude",
        "anthropic",
        "claude-desktop",
    )
    # A tier selector is an ask; nothing claims it was served.
    assert facts.requested_model == "claude-opus-4-8[1m]"
    assert facts.model is None
    assert calls == [
        {
            "root": "/Users/x/externalwebapp",
            "session_id": "sid-claude",
            "executor": "claude",
            "provider": "anthropic",
            "model_facts": SessionModelFacts(requested_model="claude-opus-4-8[1m]"),
            "entrypoint": "claude-desktop",
            "executor_version": "0.1.0",
            "machine_id": "00000000-0000-4000-8000-000000000123",
            "native_thread_id": None,
            "launch_id": None,
        }
    ]

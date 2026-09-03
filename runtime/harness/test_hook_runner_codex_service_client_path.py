"""Harness lifecycle registration uses target-aware service-client paths."""

from __future__ import annotations

from yoke_core.hooks import session_lifecycle_client
from yoke_core.hooks import session_dispatch
from yoke_contracts.session_model_facts import SessionModelFacts


def _pin_local_transport(monkeypatch) -> None:
    """These tests assert the local-subprocess wiring, which the
    https-default relay-owned registration skip
    bypasses — pin local transport so they stay hermetic on an
    https-default dev machine."""
    monkeypatch.setattr(
        session_lifecycle_client,
        "_relay_owns_registration",
        lambda: False,
    )
    monkeypatch.setattr(
        session_lifecycle_client,
        "_project_id_for_root",
        lambda _root: 1,
    )


def test_codex_register_uses_target_service_client_path(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_register(*args, **_kwargs):  # noqa: ANN001,ANN003
        calls.append(args)
        return None

    _pin_local_transport(monkeypatch)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    monkeypatch.setattr(
        "yoke_core.hooks.target.target_service_client_path",
        lambda root: "/Users/x/yoke/runtime/api/service_client.py",
    )
    monkeypatch.setattr(
        "yoke_core.hooks.service_client.register_session",
        fake_register,
    )

    err = session_dispatch._register_codex(
        "/Users/x/externalwebapp",
        "sid-codex",
        "gpt-5.5",
        "codex-desktop",
    )

    assert err == ""
    assert calls == [
        (
            "/Users/x/yoke/runtime/api/service_client.py",
            "sid-codex",
            "codex",
            "openai",
            "gpt-5.5",
            "/Users/x/externalwebapp",
            "codex-desktop",
            1,
            None,
            None,
            None,
        )
    ]


def test_codex_register_stamps_native_thread_id_from_env(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_register(*args, **_kwargs):  # noqa: ANN001,ANN003
        calls.append(args)
        return None

    _pin_local_transport(monkeypatch)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-42")
    monkeypatch.setattr(
        "yoke_core.hooks.target.target_service_client_path",
        lambda root: "/Users/x/yoke/runtime/api/service_client.py",
    )
    monkeypatch.setattr(
        "yoke_core.hooks.service_client.register_session",
        fake_register,
    )

    err = session_dispatch._register_codex(
        "/Users/x/externalwebapp",
        "sid-codex",
        "gpt-5.5",
        "codex-desktop",
    )

    assert err == ""
    assert calls[0][-1] == "thread-42"


def test_universal_register_uses_target_service_client_path(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_register(*args, **_kwargs):  # noqa: ANN001,ANN003
        calls.append(args)
        return None

    _pin_local_transport(monkeypatch)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    monkeypatch.setattr(
        "yoke_core.hooks.target.target_service_client_path",
        lambda root: "/Users/x/yoke/runtime/api/service_client.py",
    )
    monkeypatch.setattr(
        "yoke_core.hooks.service_client.register_session",
        fake_register,
    )

    err = session_lifecycle_client.register_harness_session(
        root="/Users/x/externalwebapp",
        session_id="sid-any",
        executor="claude",
        provider="anthropic",
        model_facts=SessionModelFacts(requested_model="opus"),
        entrypoint="claude-desktop",
    )

    assert err == ""
    assert calls == [
        (
            "/Users/x/yoke/runtime/api/service_client.py",
            "sid-any",
            "claude",
            "anthropic",
            SessionModelFacts(requested_model="opus"),
            "/Users/x/externalwebapp",
            "claude-desktop",
            1,
            None,
            None,
            None,
        )
    ]


def test_codex_touch_uses_target_service_client_path(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_touch(*args):  # noqa: ANN001
        calls.append(args)
        return 0

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


def test_codex_recovery_command_uses_target_service_client_path(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.hooks.target.target_service_client_path",
        lambda root: "/Users/x/yoke/runtime/api/service_client.py",
    )

    command = session_dispatch._session_begin_recovery_command(
        "sid-codex",
        "/Users/x/externalwebapp",
        "gpt-5.5",
        "codex-desktop",
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
            "model_facts": SessionModelFacts(
                requested_model="claude-opus-4-8[1m]"
            ),
            "entrypoint": "claude-desktop",
            "executor_version": "0.1.0",
            "machine_id": "00000000-0000-4000-8000-000000000123",
            "native_thread_id": None,
            "launch_id": None,
        }
    ]

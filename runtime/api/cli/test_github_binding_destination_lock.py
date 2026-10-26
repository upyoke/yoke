"""GitHub user tokens stay pinned to one selected Yoke destination."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import project_github_binding
from yoke_cli.config import (
    machine_config,
    machine_config_file,
    writer,
)
from yoke_cli.config import project_onboard_progress, project_onboard_support
from yoke_cli.transport import dispatcher
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)


from .github_binding_test_support import (
    _two_service_config,
    _install_observed_authority,
)


def test_binding_cli_holds_destination_through_token_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _two_service_config(tmp_path)
    attempted, switched, threads = _install_observed_authority(
        monkeypatch,
        config,
        project_github_binding.github_binding_auth,
    )

    def dispatch(_function_id, payload, *_args, **_kwargs):
        threads[0].start()
        assert attempted.wait(1)
        assert not switched.is_set()
        assert machine_config.active_env(config) == "service-a"
        assert payload["expected_api_url"] == "https://api.github.com"
        assert payload["github_user_access_token"] == "service-a-user-token"
        return 0

    monkeypatch.setattr(project_github_binding, "_dispatch", dispatch)
    assert (
        project_github_binding.projects_github_binding_bind(
            [
                "--project",
                "demo",
                "--installation-id",
                "1",
                "--repository-id",
                "2",
                "--github-repo",
                "owner/demo",
            ]
        )
        == 0
    )

    threads[0].join(2)
    assert switched.is_set()
    assert machine_config.active_env(config) == "service-b"


def test_binding_cli_holds_actor_credential_through_token_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    config = _two_service_config(tmp_path)
    attempted = Event()
    rotated = Event()
    real_operation_lock = machine_config_file.exclusive_lock

    @contextmanager
    def observed_operation_lock(path=None):
        if current_thread().name == "actor-credential-rotation":
            attempted.set()
        with real_operation_lock(path):
            yield

    monkeypatch.setattr(
        machine_config_file,
        "exclusive_lock",
        observed_operation_lock,
    )

    @contextmanager
    def locked_authority(*_args, **_kwargs):
        with machine_config_file.exclusive_lock(config):
            yield SimpleNamespace(
                api_url="https://api.github.com",
                token=SimpleNamespace(access_token="service-a-user-token"),
            )

    monkeypatch.setattr(
        project_github_binding.github_binding_auth,
        "locked_profile_bound_access_for_binding",
        locked_authority,
    )

    def rotate() -> None:
        writer.set_credential("service-a", token="rotated-actor", path=config)
        rotated.set()

    thread = Thread(
        target=rotate,
        name="actor-credential-rotation",
        daemon=True,
    )

    def dispatch(_function_id, payload, *_args, **_kwargs):
        thread.start()
        assert attempted.wait(1)
        assert not rotated.is_set()
        assert payload["github_user_access_token"] == "service-a-user-token"
        return 0

    monkeypatch.setattr(project_github_binding, "_dispatch", dispatch)
    assert (
        project_github_binding.projects_github_binding_bind(
            [
                "--project",
                "demo",
                "--installation-id",
                "1",
                "--repository-id",
                "2",
                "--github-repo",
                "owner/demo",
            ]
        )
        == 0
    )

    thread.join(2)
    assert rotated.is_set()


def test_onboard_binding_holds_destination_through_token_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _two_service_config(tmp_path)
    attempted, switched, threads = _install_observed_authority(
        monkeypatch,
        config,
        project_onboard_progress.github_binding_auth,
    )
    monkeypatch.setattr(
        project_onboard_progress.machine_config,
        "github_config",
        lambda _path: {
            "repositories": [
                {
                    "installation_id": 1,
                    "repository_id": 2,
                    "full_name": "owner/demo",
                }
            ]
        },
    )

    def dispatch(function_id, payload, _config_path, **_kwargs):
        if function_id == "projects.github_binding.bind":
            threads[0].start()
            assert attempted.wait(1)
            assert not switched.is_set()
            assert machine_config.active_env(config) == "service-a"
            assert payload["expected_api_url"] == "https://api.github.com"
            assert payload["github_user_access_token"] == "service-a-user-token"
            return {"binding": {"status": "active"}}
        return {"project": payload}

    monkeypatch.setattr(project_onboard_progress, "dispatch", dispatch)
    report = project_onboard_progress.store_github_binding(
        None,
        "app-binding",
        {"id": 41, "slug": "demo", "name": "Demo"},
        {"choice": "app-binding", "github_repo": "owner/demo"},
        config,
    )

    threads[0].join(2)
    assert report["binding"] == "active"
    assert switched.is_set()
    assert machine_config.active_env(config) == "service-b"


@pytest.mark.parametrize(
    ("service_api_url", "local_connection_selected"),
    (
        (None, True),
        ("https://service-b.yoke.example/v1", False),
    ),
)
def test_onboard_binding_uses_the_run_selected_connection_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    service_api_url: str | None,
    local_connection_selected: bool,
) -> None:
    config = _two_service_config(tmp_path)
    seen: dict[str, object] = {}

    @contextmanager
    def locked_authority(**kwargs):
        seen.update(kwargs)
        yield SimpleNamespace(
            api_url="https://api.github.com",
            token=SimpleNamespace(access_token="selected-user-token"),
        )

    monkeypatch.setattr(
        project_onboard_progress.github_binding_auth,
        "locked_profile_bound_access_for_binding",
        locked_authority,
    )
    monkeypatch.setattr(
        project_onboard_progress.machine_config,
        "github_config",
        lambda _path: {
            "repositories": [
                {
                    "installation_id": 1,
                    "repository_id": 2,
                    "full_name": "owner/demo",
                }
            ]
        },
    )
    monkeypatch.setattr(
        project_onboard_progress,
        "dispatch",
        lambda *_args, **_kwargs: {"binding": {"status": "active"}},
    )

    report = project_onboard_progress.store_github_binding(
        None,
        "app-binding",
        {"id": 41, "slug": "demo", "name": "Demo"},
        {"choice": "app-binding", "github_repo": "owner/demo"},
        config,
        service_api_url=service_api_url,
        local_connection_selected=local_connection_selected,
    )

    assert report["binding"] == "active"
    assert seen == {
        "config_path": config,
        "service_api_url": service_api_url,
        "local_connection_selected": local_connection_selected,
    }


def test_onboard_dispatch_redacts_every_echo_of_transient_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "service-a-user-token"

    def hostile_dispatcher(**kwargs):
        assert kwargs["sensitive_values"] == (token,)
        raw = FunctionCallResponse(
            success=False,
            function=kwargs["function_id"],
            version="1",
            request_id="request-1",
            error=FunctionError(
                code="hostile_echo",
                message=f"{token} / {token} / {token}",
                recovery_hint=f"never repeat {token}",
            ),
        )
        return dispatcher._settle_response(raw, kwargs["sensitive_values"])

    monkeypatch.setattr(
        project_onboard_support,
        "call_dispatcher",
        hostile_dispatcher,
    )
    with pytest.raises(project_onboard_support.ProjectDispatchError) as caught:
        project_onboard_support.dispatch(
            "projects.github_binding.bind",
            {"github_user_access_token": token},
            None,
            sensitive_values=(token,),
        )

    message = str(caught.value)
    assert token not in message
    assert message.count("<redacted>") == 3

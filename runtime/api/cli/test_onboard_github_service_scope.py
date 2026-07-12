"""Pre-Apply GitHub user access stays pinned to the selected Yoke service."""

from __future__ import annotations

from argparse import Namespace

import pytest

from yoke_cli.commands.adapters import onboard_github_requests
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_project_github_inputs
from yoke_cli.config import onboard_reuse_state
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import project_onboard_apply
from yoke_cli.config.project_publish_support import PublishRequest


class _Token:
    access_token = "transient-user-access"


def test_wizard_uses_inflight_service_before_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    result = type("Result", (), {
        "machine_github_choice": onboard_machine_github.CHOICE_CONNECT,
        "machine_github_verification": {"ok": True, "ready": True},
        "config_path": "/tmp/yoke-config.json",
        "api_url": "https://api.stage.upyoke.com",
        "destination": onboard_destinations.DESTINATION_HOSTED,
    })()
    monkeypatch.setattr(
        github_state.machine_config,
        "github_config",
        lambda _path: {"profile_source": "service"},
    )
    monkeypatch.setattr(
        github_state.github_local_user_access,
        "access_token",
        lambda **kwargs: seen.update(kwargs) or _Token(),
    )

    assert github_state.user_access_token(result) == "transient-user-access"
    assert seen == {
        "config_path": "/tmp/yoke-config.json",
        "service_api_url": "https://api.stage.upyoke.com",
        "local_connection_selected": False,
    }


def test_noninteractive_onboard_uses_requested_service_before_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    parsed = Namespace(
        config_path="/tmp/yoke-config.json",
        api_url="https://team.yoke.example",
    )
    monkeypatch.setattr(
        onboard_github_requests.github_local_user_access,
        "access_token",
        lambda **kwargs: seen.update(kwargs) or _Token(),
    )

    assert onboard_github_requests.github_user_access_token(
        parsed, required=True,
    ) == "transient-user-access"
    assert seen == {
        "config_path": "/tmp/yoke-config.json",
        "service_api_url": "https://team.yoke.example",
        "local_connection_selected": False,
    }


def test_non_https_service_is_not_collapsed_to_ambient_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    parsed = Namespace(
        config_path="/tmp/yoke-config.json",
        api_url="http://127.0.0.1:9444",
    )
    monkeypatch.setattr(
        onboard_github_requests.github_local_user_access,
        "access_token",
        lambda **kwargs: seen.update(kwargs) or _Token(),
    )

    onboard_github_requests.github_user_access_token(parsed, required=True)

    assert seen["service_api_url"] == "http://127.0.0.1:9444"
    assert seen["local_connection_selected"] is False


def test_noninteractive_profile_failure_uses_command_token_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_error = (
        onboard_github_requests.github_local_user_access.GitHubLocalUserAccessError
    )
    parsed = Namespace(
        config_path="/tmp/yoke-config.json",
        api_url="https://api.stage.upyoke.com",
    )
    monkeypatch.setattr(
        onboard_github_requests.github_local_user_access,
        "access_token",
        lambda **_kwargs: (_ for _ in ()).throw(
            local_error("selected connection unavailable")
        ),
    )

    with pytest.raises(
        onboard_github_requests.github_user_tokens.GitHubUserTokenError,
        match="selected connection unavailable",
    ):
        onboard_github_requests.github_user_access_token(parsed, required=True)


def test_noninteractive_missing_connection_scope_fails_closed() -> None:
    parsed = Namespace(config_path="/tmp/yoke-config.json", api_url="")

    with pytest.raises(
        onboard_github_requests.github_user_tokens.GitHubUserTokenError,
        match="does not identify",
    ):
        onboard_github_requests.github_user_access_token(parsed, required=True)


def test_wizard_explicit_local_scope_does_not_infer_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    result = type("Result", (), {
        "machine_github_choice": onboard_machine_github.CHOICE_CONNECT,
        "machine_github_verification": {"ok": True, "ready": True},
        "config_path": "/tmp/yoke-config.json",
        "api_url": "",
        "destination": onboard_destinations.DESTINATION_LOCAL,
    })()
    monkeypatch.setattr(
        github_state.machine_config,
        "github_config",
        lambda _path: {"profile_source": "local_product"},
    )
    monkeypatch.setattr(
        github_state.github_local_user_access,
        "access_token",
        lambda **kwargs: seen.update(kwargs) or _Token(),
    )

    assert github_state.user_access_token(result) == "transient-user-access"
    assert seen == {
        "config_path": "/tmp/yoke-config.json",
        "service_api_url": None,
        "local_connection_selected": True,
    }


def test_apply_hydration_keeps_selected_service_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    publish = PublishRequest(
        owner="octocat",
        name="widget",
        user_login="octocat",
        token=None,
        use_machine_github=True,
    )
    monkeypatch.setattr(
        onboard_project_github_inputs.machine_config,
        "github_config",
        lambda _path: {
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "installations": [],
        },
    )
    monkeypatch.setattr(
        onboard_project_github_inputs.github_local_user_access,
        "access_token",
        lambda **kwargs: seen.update(kwargs) or _Token(),
    )

    hydrated = onboard_project_github_inputs.hydrate_machine_github_inputs(
        {"publish": publish},
        "/tmp/yoke-config.json",
        service_api_url="https://api.stage.upyoke.com",
    )

    assert hydrated["publish"].token == "transient-user-access"
    assert seen == {
        "config_path": "/tmp/yoke-config.json",
        "service_api_url": "https://api.stage.upyoke.com",
        "local_connection_selected": False,
    }


def test_source_dev_token_keeps_explicit_local_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        onboard_project.github_local_user_access,
        "access_token",
        lambda **kwargs: seen.update(kwargs) or _Token(),
    )

    assert onboard_project._github_user_access_token(
        "/tmp/yoke-config.json",
        local_connection_selected=True,
    ) == "transient-user-access"
    assert seen == {
        "config_path": "/tmp/yoke-config.json",
        "service_api_url": None,
        "local_connection_selected": True,
    }


@pytest.mark.parametrize(
    ("service_api_url", "local_connection_selected"),
    ((None, True), ("https://api.stage.upyoke.com", False)),
)
def test_final_apply_binding_keeps_the_selected_connection_scope(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    service_api_url: str | None,
    local_connection_selected: bool,
) -> None:
    seen: dict[str, object] = {}
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(
        project_onboard_apply.progress_steps,
        "store_github_binding",
        lambda *_args, **kwargs: seen.update(kwargs) or {"binding": "active"},
    )
    monkeypatch.setattr(
        project_onboard_apply,
        "project_mapping_needs_write",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        project_onboard_apply.source_dev,
        "is_yoke_source_checkout",
        lambda _root: False,
    )
    monkeypatch.setattr(
        project_onboard_apply.install_runner,
        "install",
        lambda *_args, **_kwargs: {"machine_config_newly_registered": False},
    )
    monkeypatch.setattr(
        project_onboard_apply.machine_config,
        "github_config",
        lambda _path: {},
    )
    monkeypatch.setattr(
        project_onboard_apply,
        "applied_report",
        lambda *_args, **_kwargs: {"applied": True},
    )

    project_onboard_apply.finish_after_dispatch(
        operation="onboard.project",
        root=root,
        result={"project": {"id": 41, "slug": "demo"}},
        github_adoption={"choice": "app-binding"},
        config_path=tmp_path / "config.json",
        progress=None,
        github_auth_target="app-binding",
        scaffold_action="project-install-scaffold",
        reuse_github_auth=False,
        service_api_url=service_api_url,
        local_connection_selected=local_connection_selected,
    )

    assert seen["service_api_url"] == service_api_url
    assert seen["local_connection_selected"] is local_connection_selected


def test_reuse_requires_exact_selected_service_profile(tmp_path) -> None:
    refresh = tmp_path / "github-refresh"
    refresh.write_text("refresh\n", encoding="utf-8")
    payload = {
        "github": {
            "api_url": "https://api.github.com",
            "profile_source": "service",
            "profile_service_api_url": "https://api.prod.upyoke.com",
            "authorization": {
                "refresh_credential_ref": str(refresh),
            },
        },
    }
    requested = {
        "choice": onboard_machine_github.CHOICE_CONNECT,
        "api_url": "https://api.github.com",
        "authorization_source": {"kind": "github_app"},
    }

    assert onboard_reuse_state._machine_github_matches(
        payload,
        requested,
        service_api_url="https://api.stage.upyoke.com",
        local_connection_selected=False,
    ) is False
    assert onboard_reuse_state._machine_github_matches(
        payload,
        requested,
        service_api_url="https://api.prod.upyoke.com",
        local_connection_selected=False,
    ) is True


def test_reuse_distinguishes_explicit_local_from_hosted(tmp_path) -> None:
    refresh = tmp_path / "github-refresh"
    refresh.write_text("refresh\n", encoding="utf-8")
    payload = {
        "github": {
            "api_url": "https://api.github.com",
            "profile_source": "local_product",
            "authorization": {
                "refresh_credential_ref": str(refresh),
            },
        },
    }
    requested = {
        "choice": onboard_machine_github.CHOICE_CONNECT,
        "api_url": "https://api.github.com",
        "authorization_source": {"kind": "github_app"},
    }

    assert onboard_reuse_state._machine_github_matches(
        payload,
        requested,
        service_api_url=None,
        local_connection_selected=True,
    ) is True
    assert onboard_reuse_state._machine_github_matches(
        payload,
        requested,
        service_api_url="https://api.upyoke.com",
        local_connection_selected=False,
    ) is False

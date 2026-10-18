"""Lane merge carries the machine's GitHub user authority."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.commands import merge_item_local_runtime as item_runtime
from yoke_cli.commands import merge_worktree_local_runtime as local_runtime
from yoke_cli.config import github_merge_path_binding as merge_path_binding
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import project_github_auth_tokens
from yoke_core.domain.github_app_dispatch_context import (
    LOCAL_API_ENDPOINT,
    LOCAL_USER_TOKEN_PROVIDER,
)
from yoke_core.tools import watch_merge

_LANE_ARGS = [f"YOK-{42}", "main", f"YOK-{42}"]


def _configure_https_machine(monkeypatch) -> None:
    monkeypatch.setattr(
        merge_path_binding.machine_config,
        "github_config",
        lambda _config_path=None: {"api_url": "https://api.github.com"},
    )
    monkeypatch.setattr(
        merge_path_binding.github_app_public_profile,
        "selected_https_service_api_url",
        lambda _config_path=None: "https://api.stage.upyoke.test",
    )
    monkeypatch.setenv(ENV_OVERRIDE, "prod")
    monkeypatch.setattr(item_runtime.machine_config, "active_env", lambda: "prod")
    monkeypatch.setattr(
        item_runtime.machine_config,
        "active_connection",
        lambda: {"transport": "https"},
    )


def _engine(monkeypatch, child_main) -> None:
    real_import = local_runtime.importlib.import_module

    def import_module(name: str):
        if name == "yoke_core.engines.merge_worktree":
            return SimpleNamespace(main=child_main)
        return real_import(name)

    monkeypatch.setattr(local_runtime.importlib, "import_module", import_module)


def test_watch_merge_worktree_runs_the_authority_binding_runtime() -> None:
    assert (
        watch_merge.SUBCOMMAND_MODULES["merge-worktree"]
        == "yoke_cli.commands.merge_worktree_local_runtime"
    )


def test_engine_runs_with_only_machine_user_authorization(monkeypatch) -> None:
    _configure_https_machine(monkeypatch)
    monkeypatch.setattr(
        item_runtime.github_local_user_access,
        "access_token",
        lambda **_kwargs: SimpleNamespace(access_token="user-token"),
    )

    def app_credentials(*_args, **_kwargs):
        raise AssertionError("lane merge must not read laptop App credentials")

    monkeypatch.setattr(
        project_github_auth_tokens, "read_app_credentials", app_credentials
    )

    def child_main(argv):
        assert argv == _LANE_ARGS
        endpoint = LOCAL_API_ENDPOINT.get()
        provider = LOCAL_USER_TOKEN_PROVIDER.get()
        assert endpoint is not None
        assert endpoint.base_url == "https://api.github.com"
        assert provider is not None
        assert provider() == "user-token"
        return 5

    _engine(monkeypatch, child_main)

    assert local_runtime.main(list(_LANE_ARGS)) == 5
    assert LOCAL_API_ENDPOINT.get() is None
    assert LOCAL_USER_TOKEN_PROVIDER.get() is None


def test_missing_user_authorization_refuses_with_reconnect_recovery(
    monkeypatch, capsys
) -> None:
    _configure_https_machine(monkeypatch)

    def no_authorization(**_kwargs):
        raise item_runtime.github_local_user_access.GitHubLocalUserAccessError(
            "not connected"
        )

    monkeypatch.setattr(
        item_runtime.github_local_user_access, "access_token", no_authorization
    )

    def child_main(_argv):
        LOCAL_USER_TOKEN_PROVIDER.get()()
        return 0

    _engine(monkeypatch, child_main)

    assert local_runtime.main(list(_LANE_ARGS)) == 1
    assert merge_path_binding.RECONNECT_RECOVERY in capsys.readouterr().err


def test_help_needs_no_authority(monkeypatch) -> None:
    def no_authority():
        raise AssertionError("help must not bind GitHub authority")

    monkeypatch.setattr(local_runtime, "machine_github_user_authority", no_authority)
    _engine(monkeypatch, lambda argv: 0 if argv == ["--help"] else 9)

    assert local_runtime.run(["--help"]) == 0

from __future__ import annotations

import json

import pytest

from yoke_contracts.machine_config import schema as contract


def test_canonical_example_is_valid_machine_config() -> None:
    payload = contract.canonical_example_payload()

    assert payload["schema_version"] == 1
    assert payload["active_env"] == "prod"
    assert payload["connections"]["prod"]["transport"] == "https"
    assert payload["connections"]["prod"][contract.PROD_FLAG_KEY] is True
    assert payload["connections"]["source-dev-admin"]["transport"] == "local-postgres"
    assert payload["connections"]["source-dev-admin"][contract.PROD_FLAG_KEY] is False
    assert payload["connections"]["stage"]["transport"] == "https"
    assert payload["connections"]["stage"][contract.PROD_FLAG_KEY] is False
    board = next(iter(payload["projects"].values()))["board"]
    assert set(board) == {"render_path", "scope"}
    assert contract.validate_payload(payload) == []
    assert json.loads(contract.canonical_example_text()) == payload


def test_github_app_authorization_config_is_valid_without_env_connection() -> None:
    payload = {
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "app_slug": "yoke",
            "client_id": "Iv1.example",
            "authorization": {
                "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "refresh_credential_ref": "~/.yoke/secrets/github.user-refresh",
                "github_user_id": 1001,
                "login": "machine-user",
                "status": "authorized",
            },
        },
    }

    assert contract.validate_payload(payload) == []


def test_github_github_auth_machine_config_is_rejected() -> None:
    payload = {
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "credential_source": {
                "kind": "token_file",
                "path": "~/.yoke/secrets/github.token",
            },
        },
    }

    codes = {issue.code for issue in contract.validate_payload(payload)}

    assert "github_key_invalid" in codes
    assert "github_authorization_required" in codes


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("api_url", "http://api.github.example", "github_api_url_invalid"),
        ("api_url", "https://user@api.github.example", "github_api_url_invalid"),
        ("web_url", "https://github.example?next=evil", "github_web_url_invalid"),
    ],
)
def test_github_app_config_rejects_unsafe_endpoints(
    key: str, value: str, code: str,
) -> None:
    payload = contract.canonical_example_payload()
    payload["github"][key] = value

    codes = {issue.code for issue in contract.validate_payload(payload)}

    assert code in codes


@pytest.mark.parametrize(
    ("section", "key", "code"),
    [
        ("github", "app_id", "github_app_id_invalid"),
        ("authorization", "github_user_id", "github_authorization_user_id_invalid"),
        ("installation", "installation_id", "github_installation_id_invalid"),
        ("installation", "account_id", "github_installation_account_id_invalid"),
        ("repository", "repository_id", "github_repository_id_invalid"),
        ("repository", "installation_id", "github_repository_installation_id_invalid"),
    ],
)
def test_github_app_config_rejects_boolean_ids(
    section: str, key: str, code: str,
) -> None:
    github = {
        "api_url": contract.DEFAULT_GITHUB_API_URL,
        "web_url": contract.DEFAULT_GITHUB_WEB_URL,
        "app_slug": "yoke",
        "client_id": "Iv1.example",
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": "~/.yoke/secrets/github-app-user.json",
            "status": "authorized",
            "github_user_id": 1,
        },
        "installations": [{
            "installation_id": 2, "account_id": 3,
            "account_login": "octo-org", "repository_selection": "selected",
        }],
        "repositories": [{
            "repository_id": 4, "installation_id": 2,
            "full_name": "octo-org/app",
        }],
    }
    targets = {
        "github": github,
        "authorization": github["authorization"],
        "installation": github["installations"][0],
        "repository": github["repositories"][0],
    }
    targets[section][key] = True

    codes = {
        issue.code for issue in contract.validate_payload({
            "schema_version": 1, "github": github,
        })
    }

    assert code in codes


def test_github_app_config_rejects_unsafe_app_slug() -> None:
    payload = contract.canonical_example_payload()
    payload["github"]["app_slug"] = "../../install?next=evil"

    codes = {issue.code for issue in contract.validate_payload(payload)}

    assert "github_app_slug_invalid" in codes


def test_requires_positive_integer_project_id() -> None:
    issues = contract.validate_payload({
        "schema_version": 1,
        "active_env": "prod",
        "connections": {
            "prod": {
                "transport": "local-postgres",
                "credential_source": {"kind": "env", "name": "YOKE_PG_DSN"},
            },
        },
        "projects": {"/repo": {}},
    })

    assert any(issue.code == "project_id_required" for issue in issues)


def test_project_entry_rejects_slug_copy() -> None:
    payload = contract.canonical_example_payload()
    project = next(iter(payload["projects"].values()))
    project["project"] = "yoke"

    issues = contract.validate_payload(payload)

    assert any(issue.code == "project_key_invalid" for issue in issues)


def test_project_board_rejects_art_path() -> None:
    payload = contract.canonical_example_payload()
    project = next(iter(payload["projects"].values()))
    project["board"]["art_path"] = ".yoke/board-art"

    issues = contract.validate_payload(payload)

    assert any(issue.code == "project_board_key_invalid" for issue in issues)


def test_env_override_routes_to_configured_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = contract.canonical_example_payload()

    monkeypatch.setenv(contract.ENV_OVERRIDE, "stage")

    assert contract.selected_env(payload) == "stage"
    connection = contract.active_connection(payload)
    assert connection["env"] == "stage"
    assert connection["transport"] == "https"


def test_active_connection_rejects_unconfigured_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = contract.canonical_example_payload()

    monkeypatch.setenv(contract.ENV_OVERRIDE, "nope")

    with pytest.raises(contract.MachineConfigContractError, match="nope"):
        contract.active_connection(payload)


def test_validate_flags_unknown_active_and_requested_env() -> None:
    payload = contract.canonical_example_payload()
    payload["active_env"] = "ghost"

    codes = {issue.code for issue in
             contract.validate_payload(payload, explicit_env="phantom")}

    assert "active_env_unknown" in codes
    assert "env_unknown" in codes


def test_validate_rejects_non_boolean_prod_flag() -> None:
    payload = contract.canonical_example_payload()
    payload["connections"]["stage"][contract.PROD_FLAG_KEY] = "false"

    issues = contract.validate_payload(payload)

    assert any(issue.code == "prod_flag_invalid" for issue in issues)


def test_validate_requires_connections_and_active_env() -> None:
    codes = {issue.code for issue in
             contract.validate_payload({"schema_version": 1})}

    assert "connections_required" in codes
    assert "active_env_required" in codes


def test_project_entry_matches_worktree_path(tmp_path) -> None:
    repo = tmp_path / "repo"
    worktree = repo / ".worktrees" / "branch"
    worktree.mkdir(parents=True)
    payload = {
        "projects": {
            str(repo.resolve()): {"project_id": 1},
        }
    }

    assert contract.project_entry_for_checkout(payload, worktree)["project_id"] == 1


def test_incomplete_tunnel_block_is_a_validation_error() -> None:
    payload = contract.canonical_example_payload()
    tunnel = payload["connections"]["source-dev-admin"]["postgres"]["tunnel"]
    del tunnel["remote_port"]
    del tunnel["identity_file"]

    issues = contract.validate_payload(payload)

    [issue] = [i for i in issues if i.code == "tunnel_incomplete"]
    assert "identity_file" in issue.message
    assert "remote_port" in issue.message


def test_absent_tunnel_block_is_valid() -> None:
    payload = contract.canonical_example_payload()
    del payload["connections"]["source-dev-admin"]["postgres"]["tunnel"]

    assert contract.validate_payload(payload) == []


def test_local_postgres_envs_lists_only_local_transports() -> None:
    payload = contract.canonical_example_payload()
    payload["connections"]["cloud-beta"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: False,
        "credential_source": {"kind": "env", "name": "X"},
    }
    payload["connections"]["prod-db-admin"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: True,
        "credential_source": {"kind": "env", "name": "Y"},
    }

    assert contract.local_postgres_envs(payload) == [
        "cloud-beta", "source-dev-admin",
    ]
    assert contract.local_postgres_envs(payload, include_prod=True) == [
        "cloud-beta", "prod-db-admin", "source-dev-admin",
    ]
    assert contract.local_postgres_envs({}) == []
    assert contract.local_postgres_envs(None) == []


def test_env_override_teaching_names_why_envs_and_recipe() -> None:
    payload = contract.canonical_example_payload()
    payload["connections"]["prod-db-admin"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: True,
        "credential_source": {"kind": "env", "name": "YOKE_PROD_DSN"},
    }
    payload["active_env"] = "stage"

    # Example command: direct SQL is a genuinely local-postgres-only
    # surface (wrapped `yoke` reads relay over https).
    recipe = 'python3 -m yoke_core.cli.db_router query "SELECT 1"'
    text = contract.env_override_teaching(
        payload, selected_env="stage", transport="https",
        command=recipe,
    )

    assert "'stage'" in text and "https" in text
    assert "requires a local-postgres env" in text
    assert f"{contract.ENV_OVERRIDE}=source-dev-admin {recipe}" in text
    assert "configured local-postgres envs: source-dev-admin" in text
    assert "--env source-dev-admin" in text
    assert "prod-db-admin" not in text


def test_env_override_teaching_without_local_env_teaches_config() -> None:
    payload = contract.canonical_example_payload()
    del payload["connections"]["source-dev-admin"]
    payload["connections"]["prod-db-admin"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: True,
        "credential_source": {"kind": "env", "name": "YOKE_PROD_DSN"},
    }

    text = contract.env_override_teaching(
        payload, selected_env="stage", transport="https",
    )

    assert "No local-postgres env is configured" in text
    assert "yoke config example" in text
    assert "prod-db-admin" not in text


def test_invocation_recipe_reconstructs_module_and_script_shapes() -> None:
    module_form = contract._invocation_recipe(
        argv=["/x/db_router.py", "query", "SELECT 1"],
        main_spec_name="yoke_core.cli.db_router",
    )
    assert module_form == "python3 -m yoke_core.cli.db_router query 'SELECT 1'"

    package_form = contract._invocation_recipe(
        argv=["/x/__main__.py"], main_spec_name="some.pkg.__main__",
    )
    assert package_form == "python3 -m some.pkg"

    script_form = contract._invocation_recipe(
        argv=["/usr/local/bin/yoke", "status"],
        main_spec_name="",
    )
    assert script_form == "yoke status"

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
    entry = payload["projects"][0]
    assert entry["checkout"] and entry["env"] == "prod"
    assert set(entry["board"]) == {"render_path", "scope"}
    assert contract.validate_payload(payload) == []
    assert json.loads(contract.canonical_example_text()) == payload


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
    project = payload["projects"][0]
    project["project"] = "yoke"

    issues = contract.validate_payload(payload)

    assert any(issue.code == "project_key_invalid" for issue in issues)


def test_project_board_rejects_art_path() -> None:
    payload = contract.canonical_example_payload()
    project = payload["projects"][0]
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

    # env=None keeps this focused on path-candidate matching; env-scoping is
    # covered by the env-aware resolution tests below.
    assert contract.project_entry_for_checkout(
        payload, worktree, env=None)["project_id"] == 1


def test_project_entry_scoped_to_matching_env(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    payload = {
        "active_env": "prod",
        "projects": {
            str(repo.resolve()): {"project_id": 1, "env": "prod"},
        },
    }

    # Same checkout, per-universe id: resolves under its own env, falls
    # through (no silent wrong-universe project) under any other env.
    assert contract.project_entry_for_checkout(
        payload, repo, env="prod")["project_id"] == 1
    assert contract.project_entry_for_checkout(payload, repo, env="local") == {}


def test_project_entry_untagged_matches_active_env_only(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    payload = {
        "active_env": "prod",
        "projects": {
            str(repo.resolve()): {"project_id": 1},
        },
    }

    # A not-yet-stamped legacy entry resolves under the active env, and only
    # the active env, so behavior is unchanged before stamping but a non-active
    # env no longer silently resolves to the wrong universe.
    assert contract.project_entry_for_checkout(
        payload, repo, env="prod")["project_id"] == 1
    assert contract.project_entry_for_checkout(payload, repo, env="local") == {}


def test_same_project_id_coexists_under_distinct_envs(tmp_path) -> None:
    prod_repo = tmp_path / "prod-checkout"
    local_repo = tmp_path / "local-checkout"
    for repo in (prod_repo, local_repo):
        repo.mkdir()
    payload = {
        "active_env": "prod",
        "projects": {
            str(prod_repo.resolve()): {"project_id": 1, "env": "prod"},
            str(local_repo.resolve()): {"project_id": 1, "env": "local"},
        },
    }

    assert contract.project_entry_for_checkout(
        payload, prod_repo, env="prod")["project_id"] == 1
    assert contract.project_entry_for_checkout(
        payload, local_repo, env="local")["project_id"] == 1
    # The local checkout does not leak into the prod universe.
    assert contract.project_entry_for_checkout(
        payload, local_repo, env="prod") == {}


def test_flat_list_resolves_same_checkout_per_env() -> None:
    # One checkout, one row per env it lives in (identical apart from env).
    payload = {
        "active_env": "prod",
        "projects": [
            {"checkout": "/co/yoke", "project_id": 1, "env": "prod"},
            {"checkout": "/co/yoke", "project_id": 1, "env": "stage"},
        ],
    }

    assert contract.project_entry_for_checkout(
        payload, "/co/yoke", env="prod")["project_id"] == 1
    assert contract.project_entry_for_checkout(
        payload, "/co/yoke", env="stage")["project_id"] == 1
    # An env with no row for this checkout falls through.
    assert contract.project_entry_for_checkout(
        payload, "/co/yoke", env="local") == {}


def test_flat_list_distinct_ids_per_env() -> None:
    # The per-universe id may differ per env; the right row wins.
    payload = {
        "active_env": "prod",
        "projects": [
            {"checkout": "/co/app", "project_id": 3, "env": "prod"},
            {"checkout": "/co/app", "project_id": 9, "env": "stage"},
        ],
    }

    assert contract.project_entry_for_checkout(
        payload, "/co/app", env="prod")["project_id"] == 3
    assert contract.project_entry_for_checkout(
        payload, "/co/app", env="stage")["project_id"] == 9


def test_upsert_replaces_same_checkout_env_keeps_other_env() -> None:
    projects = [
        {"checkout": "/co/yoke", "project_id": 1, "env": "prod"},
        {"checkout": "/co/yoke", "project_id": 1, "env": "stage"},
    ]

    updated = contract.upsert_project_entry(
        projects, checkout="/co/yoke", project_id=7, env="prod")

    rows = sorted(((e["env"], e["project_id"]) for e in updated))
    # prod row replaced; the same checkout's stage row is untouched.
    assert rows == [("prod", 7), ("stage", 1)]


def test_upsert_drops_other_checkout_holding_same_slot() -> None:
    # A given (env, project_id) belongs to one checkout; moving it drops the old.
    projects = [
        {"checkout": "/co/old", "project_id": 1, "env": "prod"},
        {"checkout": "/co/keep", "project_id": 2, "env": "prod"},
        {"checkout": "/co/local", "project_id": 1, "env": "local"},
    ]

    updated = contract.upsert_project_entry(
        projects, checkout="/co/new", project_id=1, env="prod")

    rows = sorted((e["checkout"], e.get("env"), e["project_id"]) for e in updated)
    assert rows == [
        ("/co/keep", "prod", 2),    # different id — kept
        ("/co/local", "local", 1),  # same id, different env — kept
        ("/co/new", "prod", 1),     # /co/old dropped its (prod, 1) slot
    ]


def test_upsert_untagged_same_id_supersedes_other_checkout() -> None:
    # Registering an untagged row for id 1 supersedes another checkout's
    # untagged id-1 row (unknown env cannot be proven distinct).
    projects = [{"checkout": "/co/a", "project_id": 1}]

    updated = contract.upsert_project_entry(
        projects, checkout="/co/b", project_id=1)

    assert [e["checkout"] for e in updated] == ["/co/b"]


def test_legacy_object_shape_is_still_read(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    payload = {
        "active_env": "prod",
        "projects": {str(repo.resolve()): {"project_id": 4, "env": "prod"}},
    }

    assert contract.project_entry_for_checkout(
        payload, repo, env="prod")["project_id"] == 4
    assert contract.normalize_projects(payload["projects"]) == [
        {"checkout": str(repo.resolve()), "project_id": 4, "env": "prod"},
    ]


def test_project_env_required_and_unknown() -> None:
    payload = contract.canonical_example_payload()
    project = payload["projects"][0]
    del project["env"]
    assert any(i.code == "project_env_required"
               for i in contract.validate_payload(payload))

    project["env"] = "ghost"
    assert any(i.code == "project_env_unknown"
               for i in contract.validate_payload(payload))


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

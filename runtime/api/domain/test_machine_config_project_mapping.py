from __future__ import annotations

from yoke_contracts.machine_config import schema as contract


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

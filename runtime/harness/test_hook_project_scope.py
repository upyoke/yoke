"""Project membership is resolved on the selected machine connection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_contracts.hook_runner import project_scope
from yoke_core.hooks import codex_payload, target


@pytest.fixture
def project_map(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    config = {"active_env": "local", "connection_projects": {"local": []}}
    monkeypatch.setattr(
        project_scope.machine_config, "config_path", lambda: config_file
    )
    monkeypatch.setattr(
        project_scope.machine_config, "load_config", lambda *_args, **_kwargs: config
    )
    return config


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_connection_or_yoke_files_do_not_establish_membership(tmp_path, project_map):
    root = tmp_path / "unrelated"
    root.mkdir()
    (root / ".yoke").mkdir()
    db = root / "yoke.db"
    db.touch()
    assert project_scope.project_id_for_root(root) is None
    assert target.is_yoke_target(str(root), str(db)) is False
    assert codex_payload.is_yoke_target(str(root), str(db)) is False
    assert project_scope.project_id_for_payload({"cwd": str(root)}) is None


def test_registered_folder_and_subdirectory_share_membership(tmp_path, project_map):
    root = tmp_path / "folder"
    child = root / "child"
    child.mkdir(parents=True)
    project_map["connection_projects"]["local"] = [
        {"checkout": str(root), "project_id": 7}
    ]
    assert project_scope.project_id_for_root(root) == 7
    assert project_scope.project_id_for_root(child) == 7
    assert target.is_yoke_target(str(child), "") is True
    assert codex_payload.is_yoke_target(str(child), "") is True


def test_git_worktree_is_managed_but_nested_independent_repo_is_not(
    tmp_path, project_map
):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "initialize",
    )
    project_map["connection_projects"]["local"] = [
        {"checkout": str(root), "project_id": 7}
    ]
    lane = tmp_path / "lane"
    _git(root, "worktree", "add", "-b", "feature", str(lane))
    child = lane / "child"
    child.mkdir()
    assert project_scope.project_id_for_root(child) == 7
    nested = root / "independent"
    nested.mkdir()
    _git(nested, "init", "-b", "main")
    assert project_scope.project_id_for_root(nested) is None


def test_lane_and_main_checkout_share_membership_with_one_git_lookup(
    tmp_path, project_map, monkeypatch
):
    from yoke_contracts.machine_config import checkout

    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "initialize",
    )
    lane = tmp_path / "lane"
    _git(root, "worktree", "add", "-b", "feature", str(lane))
    project_map["connection_projects"]["local"] = [
        {"checkout": str(root), "project_id": 7}
    ]
    lookups: list[list[str]] = []
    real_run = checkout.subprocess.run

    def counted_run(args, **kwargs):
        if "worktree" in args:
            lookups.append(list(args))
        return real_run(args, **kwargs)

    monkeypatch.setattr(checkout.subprocess, "run", counted_run)

    assert project_scope.project_id_for_root(lane) == 7
    assert project_scope.project_id_for_root(root) == 7
    assert project_scope.project_id_for_root(lane) == 7
    # The lane's answer names its main checkout too, so a long-lived resident
    # asks Git once per new directory rather than twice per hook.
    assert len(lookups) == 1


@pytest.mark.parametrize("key", ["cwd", "workspace", "project_dir", "workspace_roots"])
def test_harness_workspace_facts_share_the_project_resolver(tmp_path, project_map, key):
    root = tmp_path / "managed"
    root.mkdir()
    project_map["connection_projects"]["local"] = [
        {"checkout": str(root), "project_id": 7}
    ]
    value = [str(root)] if key == "workspace_roots" else str(root)
    assert project_scope.project_id_for_payload({key: value}) == 7


def test_actual_command_workdir_wins_over_managed_session(tmp_path, project_map):
    managed = tmp_path / "managed"
    unrelated = tmp_path / "other"
    managed.mkdir()
    unrelated.mkdir()
    project_map["connection_projects"]["local"] = [
        {"checkout": str(managed), "project_id": 7}
    ]
    payload = {"cwd": str(managed), "tool_input": {"workdir": str(unrelated)}}
    assert project_scope.project_id_for_payload(payload) is None
    assert project_scope.project_id_for_payload(payload) is None
    assert (
        project_scope.project_id_for_payload(
            {
                "cwd": str(managed),
                "working_directory": str(unrelated),
            }
        )
        is None
    )


def test_unknown_guard_refusal_remains_denied_in_remote_receipt(monkeypatch):
    from yoke_core.hooks import runner
    from yoke_core.hooks.remote_entry import evaluate_remote

    monkeypatch.setattr(
        runner, "chain_for", lambda *_a: ["yoke_core.domain.lint_new_guard"]
    )
    result = evaluate_remote("PreToolUse", "{}", "codex", None, 2000)
    assert result.outcome == "denied"
    assert result.denial_audit["check_id"] == "hook_scope_unavailable"
    assert "hook_guard_scope_missing" in result.stdout
    assert "declare machine" in result.stdout


def test_empty_workspace_cannot_inherit_machine_project(project_map):
    assert project_scope.project_id_for_payload({}) is None
    assert target.is_yoke_target("", "") is False


@pytest.mark.parametrize(
    "command,denied",
    [
        ("git commit -m change", False),
        ("cat ./missing/*.py", True),
    ],
)
def test_unmapped_https_hook_relays_scope_and_preserves_local_guards(
    tmp_path,
    project_map,
    monkeypatch,
    capsys,
    command,
    denied,
):
    import json
    from runtime.api.cli.test_yoke_operations_cli_hooks import _FakeResponse
    from yoke_cli.transport.https import HttpsConnection
    from yoke_harness.hooks import relay, machine_hooks, local_subset

    root = tmp_path / "unrelated"
    root.mkdir()
    monkeypatch.setattr(
        relay, "evaluate_local_subset", local_subset.evaluate_local_subset
    )
    # The shared relay-protocol fixture pins every relay to project 7.
    monkeypatch.setattr(
        relay, "resolve_hook_project_scope", project_scope.resolve_hook_project_scope
    )
    payload = {
        "session_id": "scope-session",
        "identity_stamped": True,
        "cwd": str(root),
        "tool_name": "Bash",
        "shell": "zsh",
        "tool_input": {"command": command},
    }
    monkeypatch.setattr(relay, "stamp_hook_input", lambda _p, raw, *_a: (raw, None))
    monkeypatch.setattr(relay, "detect_executor", lambda: "codex")
    monkeypatch.setattr(relay, "_codex_capture", lambda *_a: None)
    monkeypatch.setattr(
        machine_hooks,
        "ensure_machine_hooks_for_executor",
        lambda *_a, **_k: None,
    )

    posts, audits = [], []

    def capture_http(request, **kwargs):
        posts.append(json.loads(request.data))
        return _FakeResponse(b'{"stdout": "", "exit_code": 0, "outcome": "completed"}')

    monkeypatch.setattr(
        relay, "relay_denial_audit", lambda _connection, audit: audits.append(audit)
    )
    resolutions: list[dict] = []
    real_resolve = project_scope.project_id_for_payload
    monkeypatch.setattr(
        project_scope,
        "project_id_for_payload",
        lambda request: resolutions.append(request) or real_resolve(request),
    )
    result = relay.relay_hook_event(
        "PreToolUse",
        HttpsConnection("https://example.invalid", "test-token"),
        stdin_data=json.dumps(payload),
        opener=capture_http,
    )
    assert result == 0
    output = capsys.readouterr().out
    assert ("permissionDecision" in output) is denied
    # One request resolves its project once, for the local subset and the
    # relay decision alike.
    assert len(resolutions) == 1
    assert len(posts) == (0 if denied else 1)
    assert len(audits) == (1 if denied else 0)
    if posts:
        assert posts[0]["project_id"] is None

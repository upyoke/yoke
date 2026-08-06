"""Cursor delivery through hosted and source project bundles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_contracts.cursor_permissions import (
    CURSOR_CLI_ALLOW,
    CURSOR_CLI_REL,
    CURSOR_SANDBOX_REL,
)
from yoke_core.domain import install_bundle, install_bundle_managed
from yoke_core.domain.agents_render_hooks import render_cursor_hooks_block
from yoke_core.domain.project_install_test_helpers import make_bundle
from yoke_core.tools.source_project_bundle import (
    SOURCE_MANAGED_PREFIXES,
    build_source_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTROL_ORIGIN = "control.example.test"
OPERATOR_HOOK = {"command": "echo operator-owned", "timeout": 10}


@pytest.fixture()
def machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    (home / "config.json").write_text(
        json.dumps(
            {
                "connections": {
                    "prod": {
                        "transport": "https",
                        "api_url": f"https://{CONTROL_ORIGIN}/api/orgs/acme",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return home


def _hosted_bundle() -> dict:
    root = install_bundle.server_tree_root()
    bundle = make_bundle(files=install_bundle._agent_files(root))
    bundle["hooks"] = install_bundle._hooks_block()
    bundle.update(install_bundle_managed.managed_bundle_keys(root))
    return bundle


def _read_json(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _seed_operator_cursor_content(root: Path) -> None:
    (root / "CURSOR.md").write_text("# Operator notes\n", encoding="utf-8")
    cursor = root / ".cursor"
    cursor.mkdir()
    (cursor / "hooks.json").write_text(
        json.dumps({"version": 1, "hooks": {"beforeShellExecution": [OPERATOR_HOOK]}}),
        encoding="utf-8",
    )
    (root / CURSOR_CLI_REL).write_text(
        json.dumps({"permissions": {"allow": ["Shell(make *)"], "deny": []}}),
        encoding="utf-8",
    )
    (root / CURSOR_SANDBOX_REL).write_text(
        json.dumps(
            {
                "networkPolicy": {
                    "allow": ["operator.example"],
                    "default": "allow",
                }
            }
        ),
        encoding="utf-8",
    )


def test_hosted_bundle_install_and_refresh_preserve_cursor_content(
    tmp_path: Path,
    machine_home: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _seed_operator_cursor_content(root)
    bundle = _hosted_bundle()

    first = apply_bundle(root, bundle, source="hosted-test")
    first_cursor_tree = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / ".cursor").rglob("*")
        if path.is_file()
    }
    first_cursor_tree["CURSOR.md"] = (root / "CURSOR.md").read_bytes()
    second = apply_bundle(
        root,
        bundle,
        operation="refresh",
        source="hosted-test",
    )

    assert second["hooks_added"] == {}
    refreshed_cursor_tree = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / ".cursor").rglob("*")
        if path.is_file()
    }
    refreshed_cursor_tree["CURSOR.md"] = (root / "CURSOR.md").read_bytes()
    assert refreshed_cursor_tree == first_cursor_tree
    assert (root / ".cursor/agents/yoke-engineer.md").is_file()
    hooks = _read_json(root, ".cursor/hooks.json")
    assert hooks["version"] == 1
    assert hooks["hooks"]["beforeShellExecution"][0] == OPERATOR_HOOK
    rendered = render_cursor_hooks_block()["hooks"]
    for event, entries in rendered.items():
        for entry in entries:
            assert entry in hooks["hooks"][event]
    commands = [
        entry["command"]
        for entries in hooks["hooks"].values()
        for entry in entries
        if "yoke hook evaluate" in entry["command"]
    ]
    assert commands and all("YOKE_EXECUTOR=cursor" in command for command in commands)

    cursor_md = (root / "CURSOR.md").read_text(encoding="utf-8")
    assert cursor_md.count("# Operator notes\n") == 1
    assert "<!-- BEGIN YOKE MANAGED BLOCK -->" in cursor_md
    cli_allow = _read_json(root, CURSOR_CLI_REL)["permissions"]["allow"]
    assert cli_allow[0] == "Shell(make *)"
    assert set(CURSOR_CLI_ALLOW) <= set(cli_allow)
    sandbox = _read_json(root, CURSOR_SANDBOX_REL)["networkPolicy"]
    assert sandbox == {
        "allow": ["operator.example", CONTROL_ORIGIN],
        "default": "allow",
    }
    assert first["cursor_permissions_actions"]


def test_source_bundle_covers_cursor_managed_surfaces(
    tmp_path: Path,
    machine_home: Path,
) -> None:
    bundle = build_source_bundle(
        REPO_ROOT,
        project_id=71,
        project_slug="cursor-source",
    )

    paths = {entry["path"] for entry in bundle["files"]}
    assert ".cursor/agents/yoke-architect.md" in paths
    assert ".cursor/agents/yoke-tester.md" in paths
    assert ".cursor/agents/yoke-" in SOURCE_MANAGED_PREFIXES
    assert bundle["hooks"]["cursor_hooks"] == render_cursor_hooks_block()["hooks"]
    assert {target["path"] for target in bundle["managed_markdown"]["targets"]} >= {
        "CURSOR.md"
    }

    root = tmp_path / "source-refreshed-project"
    root.mkdir()
    apply_bundle(root, bundle, operation="refresh", source="source-test")
    assert (root / ".cursor/agents/yoke-architect.md").is_file()
    assert "YOKE_EXECUTOR=cursor" in (root / ".cursor/hooks.json").read_text(
        encoding="utf-8"
    )
    assert "<!-- BEGIN YOKE MANAGED BLOCK -->" in (root / "CURSOR.md").read_text(
        encoding="utf-8"
    )
    assert set(CURSOR_CLI_ALLOW) <= set(
        _read_json(root, CURSOR_CLI_REL)["permissions"]["allow"]
    )

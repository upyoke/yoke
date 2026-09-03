from __future__ import annotations

from contextlib import nullcontext
import json

from yoke_cli.commands.adapters import packs


def test_list_prints_declared_tool_names(monkeypatch, capsys) -> None:
    monkeypatch.setattr(packs, "machine_config_path", lambda path: nullcontext())
    monkeypatch.setattr(
        packs,
        "list_packs",
        lambda **kwargs: {
            "packs": [
                {
                    "slug": "pulumi-foundation",
                    "status": "available",
                    "installed_version": None,
                    "latest_version": "1.0.0",
                    "description": "Pulumi project foundation.",
                    "prerequisites": [{"tool": "pulumi"}],
                }
            ]
        },
    )

    assert packs.packs_list(["--project", "sample"]) == 0

    assert "tools=pulumi" in capsys.readouterr().out


def test_update_forwards_repeated_accepted_current_paths(
    monkeypatch,
    capsys,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(packs, "machine_config_path", lambda path: nullcontext())

    def run_pack_operation(repo_root, **kwargs):
        captured.update({"repo_root": repo_root, **kwargs})
        return {"applied": True, "refused": False}

    monkeypatch.setattr(packs, "run_pack_operation", run_pack_operation)

    result = packs.packs_update(
        [
            "webapp-scaffold",
            "/project",
            "--project",
            "sample",
            "--accept-current",
            "app/web/src/test/setup.ts",
            "--accept-current",
            "docs/setup.md",
            "--apply",
            "--allow-missing-tools",
            "--json",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "applied": True,
        "refused": False,
    }
    assert captured == {
        "repo_root": "/project",
        "project": "sample",
        "pack": "webapp-scaffold",
        "operation": "update",
        "apply": True,
        "allow_missing_tools": True,
        "version": None,
        "session_id": None,
        "accepted_current_paths": [
            "app/web/src/test/setup.ts",
            "docs/setup.md",
        ],
    }


def test_relink_forwards_previewable_path_mapping(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(packs, "machine_config_path", lambda path: nullcontext())

    def run_pack_relink(repo_root, **kwargs):
        captured.update({"repo_root": repo_root, **kwargs})
        return {"operation": "relink", "applied": False}

    monkeypatch.setattr(packs, "run_pack_relink", run_pack_relink)

    result = packs.packs_relink(
        [
            "sample-pack",
            "/project",
            "--project",
            "sample",
            "--from",
            "old/file.py",
            "--to",
            "new/file.py",
            "--json",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "applied": False,
        "operation": "relink",
    }
    assert captured == {
        "repo_root": "/project",
        "project": "sample",
        "pack": "sample-pack",
        "from_path": "old/file.py",
        "to_path": "new/file.py",
        "apply": False,
        "session_id": None,
    }

from __future__ import annotations

from contextlib import nullcontext
import json

from yoke_cli.commands.adapters import packs


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
        "version": None,
        "session_id": None,
        "accepted_current_paths": [
            "app/web/src/test/setup.ts",
            "docs/setup.md",
        ],
    }

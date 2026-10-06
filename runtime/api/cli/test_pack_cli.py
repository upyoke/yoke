from __future__ import annotations

from contextlib import nullcontext
import json

import pytest

from yoke_cli.commands.adapters import packs
from yoke_cli.packs.catalog_source import PackCatalog
from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV

SERVED = PackCatalog(kind="served")


@pytest.fixture(autouse=True)
def _outside_source_dev_run(monkeypatch) -> None:
    monkeypatch.delenv(SOURCE_DEV_RUN_ROOT_ENV, raising=False)


def test_list_prints_declared_tool_names(monkeypatch, capsys) -> None:
    monkeypatch.setattr(packs, "machine_config_path", lambda path: nullcontext())
    monkeypatch.setattr(
        packs,
        "list_packs",
        lambda **kwargs: {
            "catalog": kwargs["catalog"].describe(),
            "packs": [
                {
                    "slug": "pulumi-foundation",
                    "status": "available",
                    "installed_version": None,
                    "latest_version": "1.0.0",
                    "description": "Pulumi project foundation.",
                    "prerequisites": [{"tool": "pulumi"}],
                }
            ],
        },
    )

    assert packs.packs_list(["--project", "sample"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("catalog=kind:served\n")
    assert "tools=pulumi" in out


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
        "catalog": SERVED,
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
        "catalog": SERVED,
    }


def test_get_refuses_lane_catalog_outside_source_dev_run(capsys) -> None:
    result = packs.packs_get(
        ["sample-pack", "/project", "--project", "sample", "--catalog", "lane"]
    )

    assert result == 1
    assert "pack-catalog-lane-unavailable" in capsys.readouterr().err


def test_get_defaults_to_the_lane_catalog_under_source_dev_run(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(packs, "machine_config_path", lambda path: nullcontext())
    monkeypatch.setenv(SOURCE_DEV_RUN_ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(
        "yoke_cli.packs.catalog_source._git_text", lambda checkout, *args: "c" * 40
    )

    def run_pack_operation(repo_root, **kwargs):
        captured.update(kwargs)
        return {"applied": False, "refused": False}

    monkeypatch.setattr(packs, "run_pack_operation", run_pack_operation)

    assert packs.packs_get(["sample-pack", "/project", "--project", "sample"]) == 0
    assert captured["catalog"] == PackCatalog(
        kind="lane", checkout=tmp_path.resolve(), commit="c" * 40
    )

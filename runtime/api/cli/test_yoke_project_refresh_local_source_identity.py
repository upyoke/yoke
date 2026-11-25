"""Source checkout origin and managed Git-hook refresh proofs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_RECEIPT_REL,
)
from yoke_cli.main import main as cli_main


REPO_ROOT = Path(__file__).resolve().parents[3]


def _git_init(root: Path) -> None:
    root.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(root), "init", "-q"],
        capture_output=True,
        text=True,
        check=True,
    )


def _project_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def test_source_process_enforces_explicit_checkout_origin(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    false_source = tmp_path / "different-yoke"
    (false_source / "runtime/harness").mkdir(parents=True)
    tools = false_source / "runtime/api/tools"
    tools.mkdir(parents=True)
    (tools.parent / "__init__.py").write_text("", encoding="utf-8")
    (tools / "__init__.py").write_text("", encoding="utf-8")
    (tools / "source_project_bundle.py").write_text(
        'raise RuntimeError("source bundle imports are not bound")\n',
        encoding="utf-8",
    )
    (false_source / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8"
    )
    before = _project_tree(target)

    rc = cli_main(
        [
            "project",
            "refresh",
            str(target),
            "--source-checkout",
            str(false_source),
            "--project-id",
            "44",
            "--project-slug",
            "origin-project",
            "--json",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert "ambient Yoke source fallback was refused" in captured.err
    assert _project_tree(target) == before


def test_source_refresh_writes_checkout_head(tmp_path, capsys) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = target / ".yoke/install-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "manifest_schema": 1,
                "yoke_version": "packaged-baseline",
                "project_id": 51,
                "project_slug": "identity-project",
                "mode": "copy",
                "files": {},
                "contract_files": {},
                "strategy_files": {},
                "created_settings_files": [],
                "hook_entries": {},
            }
        )
    )
    assert (
        cli_main(
            [
                "project",
                "refresh",
                str(target),
                "--source-checkout",
                str(REPO_ROOT),
                "--project-id",
                "51",
                "--project-slug",
                "identity-project",
                "--force",
                "--no-commit",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    receipt = json.loads((target / INSTALLED_LAYER_RECEIPT_REL).read_text())
    assert receipt["source_build"] == head

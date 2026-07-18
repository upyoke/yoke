"""Source checkout origin and managed Git-hook refresh proofs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_cli.main import main as cli_main
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_core.tools import source_project_bundle


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
    tools = false_source / "packages/yoke-core/src/yoke_core/tools"
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


def test_source_bundle_versions_selected_git_hook_content(monkeypatch) -> None:
    baseline = source_project_bundle.build_source_bundle(
        REPO_ROOT,
        project_id=50,
        project_slug="git-hook-source",
    )
    selected = git_hooks_layer.PRE_COMMIT_SHIM.replace(
        "# Hard-fails",
        "# selected source behavior\n# Hard-fails",
    )
    monkeypatch.setattr(git_hooks_layer, "PRE_COMMIT_SHIM", selected)

    refreshed = source_project_bundle.build_source_bundle(
        REPO_ROOT,
        project_id=50,
        project_slug="git-hook-source",
    )

    hooks = {entry["name"]: entry for entry in refreshed["managed_git_hooks"]}
    assert hooks["pre-commit"]["content"] == selected
    assert refreshed["yoke_version"] != baseline["yoke_version"]

"""Installed-documentation lifecycle proofs for explicit source refresh.

The explicit source-checkout refresh owns the same public documentation
corpus the server-built bundle ships. These clean-room runs prove the
corpus converges, drifted copies are rewritten, retired copies are pruned,
locally edited copies are preserved out of Yoke management, and a second
apply is inert.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from yoke_cli.main import main as cli_main
from yoke_core.domain.install_bundle import DOCS_DEST, DOCS_SOURCE
from yoke_core.domain.install_bundle_managed import docs_bundle_files

from runtime.api.tools.source_project_bundle import build_source_bundle


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_PREFIX = f"{DOCS_DEST}/"
RETIRED_DOC_REL = f"{DOCS_PREFIX}reference/retired-command.md"
RETIRED_DOC_BODY = "# Retired command\n\nUse the retired command.\n"
UNRENDERED_REL = ".github/workflows/publish.yml"
UNRENDERED_BODY = "name: publish\non: workflow_dispatch\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _write_file(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _manifest_path(root: Path) -> Path:
    return root / ".yoke/install-manifest.json"


def _read_manifest(root: Path) -> dict:
    return json.loads(_manifest_path(root).read_text(encoding="utf-8"))


def _write_manifest(root: Path, manifest: dict) -> None:
    path = _manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _seed_manifest(root: Path, project_id: int, files: dict[str, str]) -> None:
    _write_manifest(root, {
        "manifest_schema": 1,
        "yoke_version": "packaged-baseline",
        "project_id": project_id,
        "project_slug": "external-project",
        "mode": "copy",
        "files": dict(files),
        "contract_files": {},
        "strategy_files": {},
        "created_settings_files": [],
        "hook_entries": {},
    })


def _base_args(target: Path, project_id: int) -> list[str]:
    return [
        "project", "refresh", str(target),
        "--source-checkout", str(REPO_ROOT),
        "--project-id", str(project_id),
    ]


def _refresh_args(target: Path, project_id: int) -> list[str]:
    return [*_base_args(target, project_id), "--json"]


def _apply_args(target: Path, project_id: int) -> list[str]:
    return [
        *_base_args(target, project_id),
        "--force", "--no-commit", "--apply", "--json",
    ]


def _installed_docs(report_paths: list[str]) -> list[str]:
    return [rel for rel in report_paths if rel.startswith(DOCS_PREFIX)]


def test_source_bundle_renders_the_public_docs_corpus_project_neutrally() -> None:
    canonical = {
        entry["path"]: entry["content"]
        for entry in docs_bundle_files(REPO_ROOT)
    }

    bundle = build_source_bundle(
        REPO_ROOT, project_id=61, project_slug="external-project"
    )
    other = build_source_bundle(
        REPO_ROOT, project_id=62, project_slug="another-project"
    )

    rendered = {
        entry["path"]: entry["content"]
        for entry in bundle["files"]
        if entry["path"].startswith(DOCS_PREFIX)
    }
    assert canonical
    assert rendered == canonical
    assert all(path.startswith(DOCS_PREFIX) for path in canonical)
    assert DOCS_PREFIX in bundle["source_managed_prefixes"]
    # Documentation is source-derived, so two different target projects
    # receive byte-identical entries.
    assert [
        entry for entry in other["files"]
        if entry["path"].startswith(DOCS_PREFIX)
    ] == [
        entry for entry in bundle["files"]
        if entry["path"].startswith(DOCS_PREFIX)
    ]


def test_retired_doc_is_pruned_when_it_matches_the_prior_manifest(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    _write_file(target, RETIRED_DOC_REL, RETIRED_DOC_BODY)
    _seed_manifest(target, 63, {RETIRED_DOC_REL: _sha(RETIRED_DOC_BODY)})

    assert cli_main(_refresh_args(target, 63)) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["files_would_prune"] == [RETIRED_DOC_REL]
    assert _installed_docs(preview["files_would_write"])
    assert (target / RETIRED_DOC_REL).is_file()

    assert cli_main(_apply_args(target, 63)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files_pruned"] == [RETIRED_DOC_REL]
    assert not (target / RETIRED_DOC_REL).exists()
    assert RETIRED_DOC_REL not in _read_manifest(target)["files"]


def test_installed_doc_that_drifted_from_source_is_rewritten(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    _seed_manifest(target, 64, {})
    assert cli_main(_apply_args(target, 64)) == 0
    capsys.readouterr()

    manifest = _read_manifest(target)
    doc_rel = _installed_docs(sorted(manifest["files"]))[0]
    canonical_body = (
        REPO_ROOT / DOCS_SOURCE / doc_rel[len(DOCS_PREFIX):]
    ).read_text(encoding="utf-8")
    drifted = "# superseded installed copy\n"
    _write_file(target, doc_rel, drifted)
    manifest["files"][doc_rel] = _sha(drifted)
    _write_manifest(target, manifest)

    assert cli_main(_refresh_args(target, 64)) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["files_would_write"] == [doc_rel]
    assert preview["files_would_prune"] == []

    assert cli_main(_apply_args(target, 64)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files_written"] == [doc_rel]
    assert (target / doc_rel).read_text(encoding="utf-8") == canonical_body
    assert _read_manifest(target)["files"][doc_rel] == _sha(canonical_body)


def test_edited_retired_doc_is_preserved_while_unrendered_files_survive(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    edited = RETIRED_DOC_BODY + "\nOperator notes kept locally.\n"
    _write_file(target, RETIRED_DOC_REL, edited)
    _write_file(target, UNRENDERED_REL, UNRENDERED_BODY)
    _seed_manifest(target, 65, {
        RETIRED_DOC_REL: _sha(RETIRED_DOC_BODY),
        UNRENDERED_REL: _sha(UNRENDERED_BODY),
    })

    assert cli_main(_refresh_args(target, 65)) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["files_would_preserve_modified"] == [RETIRED_DOC_REL]
    assert preview["files_preserved_unrendered"] == [UNRENDERED_REL]
    assert preview["files_would_prune"] == []

    assert cli_main(_apply_args(target, 65)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files_skipped_modified"] == [RETIRED_DOC_REL]
    assert report["files_preserved_unrendered"] == [UNRENDERED_REL]
    assert report["files_pruned"] == []
    assert any(
        RETIRED_DOC_REL in warning and "no longer Yoke-managed" in warning
        for warning in report["warnings"]
    )
    assert (target / RETIRED_DOC_REL).read_text(encoding="utf-8") == edited
    refreshed = _read_manifest(target)["files"]
    assert RETIRED_DOC_REL not in refreshed
    assert refreshed[UNRENDERED_REL] == _sha(UNRENDERED_BODY)
    assert (target / UNRENDERED_REL).read_text(encoding="utf-8") == UNRENDERED_BODY


def test_second_apply_writes_and_prunes_no_documentation(
    tmp_path: Path, capsys,
) -> None:
    target = tmp_path / "external-project"
    _git_init(target)
    _seed_manifest(target, 66, {})

    assert cli_main(_apply_args(target, 66)) == 0
    first = json.loads(capsys.readouterr().out)
    written_docs = _installed_docs(first["files_written"])
    assert written_docs
    assert all((target / rel).is_file() for rel in written_docs)
    converged = _project_tree(target)

    assert cli_main(_apply_args(target, 66)) == 0
    second = json.loads(capsys.readouterr().out)
    assert _installed_docs(second["files_written"]) == []
    assert second["files_written"] == []
    assert second["files_pruned"] == []
    assert _project_tree(target) == converged

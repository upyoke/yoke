"""Tests for the db-render strategy-file install pass.

The third ownership class: missing → write; clean render → overwrite
(DB is authority); un-ingested local edit → preserve + warn; uninstall
never removes. Old bundles without ``strategy_files`` and old manifests
without the key keep working.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import project_install
from yoke_core.domain.project_install import ProjectInstallError, apply_bundle
from yoke_core.domain.project_install_test_helpers import (
    OMIT_STRATEGY,
    make_bundle,
    strategy_entry,
)
from yoke_core.domain.strategy_docs_paths import strategy_view_rel_path

MANIFEST_REL = ".yoke/install-manifest.json"

MISSION_REL = strategy_view_rel_path("MISSION")


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _manifest(repo) -> dict:
    return json.loads((repo / MANIFEST_REL).read_text(encoding="utf-8"))


def _edit_without_ingest(repo, rel: str) -> str:
    """Scribble on a rendered view's body, keeping its header line."""
    path = repo / rel
    first_line, _, _ = path.read_text(encoding="utf-8").partition("\n")
    edited = first_line + "\n# Mission\n\noperator pen edit\n"
    path.write_text(edited, encoding="utf-8")
    return edited


class TestApply:
    def test_fresh_install_writes_strategy_files(self, repo) -> None:
        report = apply_bundle(
            repo, make_bundle(strategy=[strategy_entry("MISSION", "# M\n\nv1\n")]),
        )
        assert report["strategy_files_written"] == [MISSION_REL]
        assert (repo / MISSION_REL).is_file()
        assert MISSION_REL in _manifest(repo)["strategy_files"]

    def test_byte_equal_rerender_is_unchanged(self, repo) -> None:
        entry = strategy_entry("MISSION", "# M\n\nv1\n")
        apply_bundle(repo, make_bundle(strategy=[entry]))
        report = apply_bundle(repo, make_bundle(strategy=[entry]))
        assert report["strategy_files_written"] == []
        assert report["strategy_files_unchanged"] == [MISSION_REL]
        assert report["strategy_files_preserved_edited"] == []

    def test_clean_render_is_overwritten_when_db_advanced(self, repo) -> None:
        apply_bundle(
            repo, make_bundle(strategy=[strategy_entry("MISSION", "# M\n\nv1\n")]),
        )
        newer = strategy_entry(
            "MISSION", "# M\n\nv2 from DB\n", updated_at="2026-06-11T00:00:00Z",
        )
        report = apply_bundle(repo, make_bundle(strategy=[newer]))
        assert report["strategy_files_written"] == [MISSION_REL]
        assert "v2 from DB" in (repo / MISSION_REL).read_text(encoding="utf-8")

    def test_header_only_drift_keeps_committed_file(self, repo) -> None:
        # The DB row's updated_at can advance on a no-op re-save while the body
        # stays byte-identical. A metadata-only header bump must not churn the
        # clean tracked view (observed: a freshly-cloned project showed every
        # strategy doc as git-modified with only the updated_at field changed).
        apply_bundle(repo, make_bundle(strategy=[strategy_entry(
            "MISSION", "# M\n\nv1\n", updated_at="2026-06-11T00:00:00Z",
        )]))
        before = (repo / MISSION_REL).read_text(encoding="utf-8")
        newer_header = strategy_entry(
            "MISSION", "# M\n\nv1\n", updated_at="2026-06-20T00:00:00Z",
        )
        report = apply_bundle(repo, make_bundle(strategy=[newer_header]))
        assert report["strategy_files_written"] == []
        assert report["strategy_files_unchanged"] == [MISSION_REL]
        # File untouched: keeps its original header, no spurious git diff.
        assert (repo / MISSION_REL).read_text(encoding="utf-8") == before
        assert "2026-06-11" in before

    def test_uningested_edit_is_preserved_with_warning(self, repo) -> None:
        apply_bundle(
            repo, make_bundle(strategy=[strategy_entry("MISSION", "# M\n\nv1\n")]),
        )
        edited = _edit_without_ingest(repo, MISSION_REL)
        newer = strategy_entry(
            "MISSION", "# M\n\nv2 from DB\n", updated_at="2026-06-11T00:00:00Z",
        )
        report = apply_bundle(repo, make_bundle(strategy=[newer]))
        assert report["strategy_files_preserved_edited"] == [MISSION_REL]
        assert report["strategy_files_written"] == []
        assert (repo / MISSION_REL).read_text(encoding="utf-8") == edited
        assert any("yoke strategy ingest" in w for w in report["warnings"])

    def test_headerless_local_file_is_preserved(self, repo) -> None:
        (repo / ".yoke").mkdir()
        (repo / ".yoke" / "strategy").mkdir()
        (repo / MISSION_REL).write_text(
            "# hand-authored, no header\n", encoding="utf-8",
        )
        report = apply_bundle(
            repo, make_bundle(strategy=[strategy_entry("MISSION", "# M\n\nv1\n")]),
        )
        assert report["strategy_files_preserved_edited"] == [MISSION_REL]
        assert "hand-authored" in (repo / MISSION_REL).read_text(encoding="utf-8")
        # Never recorded as installer-written.
        assert MISSION_REL not in _manifest(repo)["strategy_files"]

    def test_unsafe_strategy_paths_are_refused(self, repo) -> None:
        bad = {
            "path": ".yoke/strategy/nested/X.md",
            "content": "x",
            "install_policy": "db_render",
        }
        with pytest.raises(ProjectInstallError, match="unsafe strategy path"):
            apply_bundle(repo, make_bundle(strategy=[bad]))

    def test_unknown_strategy_policy_is_refused(self, repo) -> None:
        entry = strategy_entry("MISSION", "# M\n\nv1\n")
        entry["install_policy"] = "seed_if_missing"
        with pytest.raises(ProjectInstallError, match="strategy install_policy"):
            apply_bundle(repo, make_bundle(strategy=[entry]))


class TestTolerance:
    def test_bundle_without_strategy_key_is_tolerated(self, repo) -> None:
        report = apply_bundle(repo, make_bundle(strategy=OMIT_STRATEGY))
        assert report["strategy_files_written"] == []
        assert _manifest(repo)["strategy_files"] == {}

    def test_old_manifest_without_strategy_key_keeps_working(self, repo) -> None:
        apply_bundle(repo, make_bundle(strategy=OMIT_STRATEGY))
        manifest = _manifest(repo)
        manifest.pop("strategy_files", None)
        (repo / MANIFEST_REL).write_text(
            json.dumps(manifest), encoding="utf-8",
        )
        report = apply_bundle(
            repo, make_bundle(strategy=[strategy_entry("MISSION", "# M\n\nv1\n")]),
        )
        assert report["strategy_files_written"] == [MISSION_REL]


class TestUninstall:
    def test_uninstall_preserves_strategy_files_entirely(self, repo) -> None:
        apply_bundle(
            repo, make_bundle(strategy=[strategy_entry("MISSION", "# M\n\nv1\n")]),
        )
        report = project_install.uninstall(repo)
        assert report["strategy_files_preserved"] == [MISSION_REL]
        # The rendered view survives even though it was installer-written
        # and byte-identical to the recorded render.
        assert (repo / MISSION_REL).is_file()
        # Managed files were removed as usual.
        assert report["manifest_removed"] is True

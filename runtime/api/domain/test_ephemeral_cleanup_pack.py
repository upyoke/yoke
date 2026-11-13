"""Structural tests for the Branch Preview Hosting cleanup Pack source.

The suite covers these invariants:

* the earlier shell cleanup version remains reconstructable
* the current Python host cleanup is isolated by a preview namespace
* Compose project / volume parsing survives hyphenated slugs
* cleanup scheduling stays project-owned rather than hidden in another Pack

It exercises the current Python source after rendering it into a temporary
project copy.
"""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.domain.pack_render import render_pack_text


BRANCH_HOST_LEGACY_FILES = "packs/branch-preview-hosting/versions/1.0.0/files"
BRANCH_HOST_FILES = "packs/branch-preview-hosting/versions/1.1.0/files"


def _repo_root() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


# ---------------------------------------------------------------------------
# Fixtures — load Pack source and rendered output text
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return _repo_root()


@pytest.fixture(scope="module")
def current_cleanup_tmpl(repo_root: Path) -> str:
    tmpl = repo_root / BRANCH_HOST_FILES / "ops/ephemeral_cleanup.py"
    assert tmpl.is_file(), f"Pack source missing: {tmpl}"
    return tmpl.read_text()


class TestCurrentBranchHostCleanup:
    def test_previous_shell_version_remains_reconstructable(
        self, repo_root: Path
    ) -> None:
        source = repo_root / BRANCH_HOST_LEGACY_FILES / "ops/ephemeral-cleanup.sh.tmpl"
        assert source.is_file()

    def test_uses_preview_namespace_instead_of_project_special_cases(
        self,
        current_cleanup_tmpl: str,
    ) -> None:
        assert 'PREVIEW_NAMESPACE = "{{preview_namespace}}"' in current_cleanup_tmpl
        assert 'TTL_HOURS = int("{{preview_ttl_hours}}")' in current_cleanup_tmpl
        assert "{{project_name}}" not in current_cleanup_tmpl
        assert "PROTECTED_PROJECT" not in current_cleanup_tmpl

    def test_discovers_and_removes_only_namespaced_resources(
        self,
        current_cleanup_tmpl: str,
    ) -> None:
        assert "PREVIEW_ROOT = Path.home() / PREVIEW_NAMESPACE" in current_cleanup_tmpl
        assert 'prefix = f"{PREVIEW_NAMESPACE}-"' in current_cleanup_tmpl
        assert 'f"{PREVIEW_NAMESPACE}-{slug}"' in current_cleanup_tmpl
        assert '"--volumes"' in current_cleanup_tmpl
        assert '"--remove-orphans"' in current_cleanup_tmpl

    def test_keeps_scheduler_and_failure_policy_visible(
        self,
        current_cleanup_tmpl: str,
    ) -> None:
        assert "Scheduling is project-owned" in current_cleanup_tmpl
        assert "return 0" in current_cleanup_tmpl

    def test_rendered_program_compiles_and_parses_hyphenated_slugs(
        self, current_cleanup_tmpl: str, tmp_path: Path
    ) -> None:
        rendered = tmp_path / "ephemeral_cleanup.py"
        rendered.write_text(
            render_pack_text(
                current_cleanup_tmpl,
                {"preview_namespace": "sample-preview", "preview_ttl_hours": "24"},
            ),
            encoding="utf-8",
        )
        subprocess.run([sys.executable, "-m", "py_compile", rendered], check=True)
        namespace = runpy.run_path(str(rendered), run_name="pack_test")
        assert (
            namespace["compose_project_to_slug"]("sample-preview-feature-one")
            == "feature-one"
        )
        assert (
            namespace["image_repository_to_slug"]("sample-preview-feature-one-core")
            == "feature-one"
        )
        assert (
            namespace["volume_name_to_slug"]("sample-preview-feature-one_database")
            == "feature-one"
        )
        assert namespace["volume_name_to_slug"]("production_database") is None


# ---------------------------------------------------------------------------
# Pack boundary
# ---------------------------------------------------------------------------


class TestMaintenancePackBoundary:
    def test_latest_host_maintenance_has_no_ephemeral_setup_program(
        self, repo_root: Path
    ) -> None:
        host_files = repo_root / "packs/host-maintenance/versions/1.2.0/files"
        assert not (host_files / "ops/setup-vps-maintenance.sh.tmpl").exists()
        assert not list(host_files.rglob("*.sh.tmpl"))



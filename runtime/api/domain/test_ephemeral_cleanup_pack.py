"""Structural tests for historical and current preview cleanup Packs.

The suite audits immutable Pack source plus one rendered project-owned copy,
covering these invariants:

* the historical combined Pack remains immutable and reconstructable
* the current Python host cleanup is isolated by a preview namespace
* Compose project / volume parsing survives hyphenated slugs
* cleanup scheduling stays project-owned rather than hidden in another Pack
* deploy / teardown workflows clean up images and volumes

The suite keeps the historical shell sources reconstructable and exercises the
current Python source after rendering it into a temporary project copy.
"""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.domain.pack_render import render_pack_text


EPHEMERAL_FILES = "packs/ephemeral-environments/versions/1.0.1/files"
BRANCH_HOST_LEGACY_FILES = "packs/branch-preview-hosting/versions/1.0.0/files"
BRANCH_HOST_FILES = "packs/branch-preview-hosting/versions/1.1.0/files"
VPS_FILES = "packs/vps-hosting/versions/1.0.1/files"
PRODUCTION_FILES = "packs/production-deploy/versions/1.0.0/files"


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
def cleanup_tmpl(repo_root: Path) -> str:
    tmpl = repo_root / EPHEMERAL_FILES / "ops/ephemeral-cleanup.sh.tmpl"
    assert tmpl.is_file(), f"Pack source missing: {tmpl}"
    return tmpl.read_text()


@pytest.fixture(scope="module")
def current_cleanup_tmpl(repo_root: Path) -> str:
    tmpl = repo_root / BRANCH_HOST_FILES / "ops/ephemeral_cleanup.py"
    assert tmpl.is_file(), f"Pack source missing: {tmpl}"
    return tmpl.read_text()


@pytest.fixture(scope="module")
def provision_tmpl(repo_root: Path) -> str:
    tmpl = repo_root / VPS_FILES / "ops/provision-ec2.sh.tmpl"
    assert tmpl.is_file(), f"Pack source missing: {tmpl}"
    return tmpl.read_text()


@pytest.fixture(scope="module")
def teardown_wf(repo_root: Path) -> str:
    wf = (
        repo_root
        / EPHEMERAL_FILES
        / ".github/workflows/{{project_name}}-ephemeral-teardown.yml"
    )
    assert wf.is_file(), f"Pack workflow missing: {wf}"
    return wf.read_text()


@pytest.fixture(scope="module")
def deploy_wf(repo_root: Path) -> str:
    wf = repo_root / PRODUCTION_FILES / ".github/workflows/{{project_name}}-deploy.yml"
    assert wf.is_file(), f"Pack workflow missing: {wf}"
    return wf.read_text()


# ---------------------------------------------------------------------------
# Pack source structure (source-of-truth assertions on .sh.tmpl)
# ---------------------------------------------------------------------------


class TestCleanupPackSourceShape:
    def test_posix_shebang(self, cleanup_tmpl: str) -> None:
        assert cleanup_tmpl.splitlines()[0] == "#!/usr/bin/env sh"

    def test_uses_project_name_placeholder(self, cleanup_tmpl: str) -> None:
        assert "{{project_name}}" in cleanup_tmpl

    def test_uses_ephemeral_ttl_hours_placeholder(self, cleanup_tmpl: str) -> None:
        assert "{{ephemeral_ttl_hours}}" in cleanup_tmpl

    def test_excludes_persistent_app_and_core_projects(self, cleanup_tmpl: str) -> None:
        """cleanup must never touch the persistent app/core compose projects."""
        assert "PROTECTED_PROJECT_APP" in cleanup_tmpl
        assert "PROTECTED_PROJECT_CORE" in cleanup_tmpl
        assert "${PROJECT_NAME}-app" in cleanup_tmpl
        assert "${PROJECT_NAME}-core" in cleanup_tmpl
        # Slug-level exclusion applies to both protected projects too.
        assert "grep -v '^app$'" in cleanup_tmpl
        assert "grep -v '^core$'" in cleanup_tmpl

    def test_has_deployment_instructions_header(self, cleanup_tmpl: str) -> None:
        """Header must make scheduler ownership explicit."""
        assert "Scheduling is project-owned" in cleanup_tmpl
        assert "cron, systemd" in cleanup_tmpl

    def test_filesystem_driven_discovery(self, cleanup_tmpl: str) -> None:
        """cleanup uses filesystem-driven discovery, not Compose-only."""
        assert "EPHEMERAL_DIR" in cleanup_tmpl

    def test_discovers_slugs_from_directories(self, cleanup_tmpl: str) -> None:
        """slugs are derived from directory basenames."""
        assert "ephemeral" in cleanup_tmpl
        assert "basename" in cleanup_tmpl

    def test_compose_project_parsing_strips_prefix_exactly(
        self, cleanup_tmpl: str
    ) -> None:
        """strip the project prefix exactly, not via trailing dash."""
        assert "${_project#${PROJECT_NAME}-}" in cleanup_tmpl

    def test_volume_parsing_preserves_hyphenated_slugs(self, cleanup_tmpl: str) -> None:
        """use ``%%_*`` substring so hyphenated slugs survive."""
        assert "${_volume_rest%%_*}" in cleanup_tmpl
        # And MUST NOT use the old over-broad sed that split on [_-].
        assert "sed 's/[_-].*//'" not in cleanup_tmpl

    def test_removes_docker_images_for_stale_slugs(self, cleanup_tmpl: str) -> None:
        assert "docker rmi" in cleanup_tmpl or "docker images" in cleanup_tmpl

    def test_removes_docker_volumes_for_stale_slugs(self, cleanup_tmpl: str) -> None:
        assert "docker volume rm" in cleanup_tmpl or "docker volume ls" in cleanup_tmpl

    def test_removes_ephemeral_directories(self, cleanup_tmpl: str) -> None:
        assert "rm -rf" in cleanup_tmpl

    def test_uses_volumes_with_compose_down(self, cleanup_tmpl: str) -> None:
        """cleanup must pass --volumes to ``docker compose down``."""
        assert "--volumes" in cleanup_tmpl

    def test_exits_zero_on_partial_failures(self, cleanup_tmpl: str) -> None:
        assert "exit 0" in cleanup_tmpl

    def test_has_deployment_reference_in_header(self, cleanup_tmpl: str) -> None:
        assert "chosen scheduler" in cleanup_tmpl

    def test_heredoc_pattern_for_while_read(self, cleanup_tmpl: str) -> None:
        """use ``done <<EOF`` so counters survive the while-read loop."""
        assert "done <<EOF" in cleanup_tmpl
        # And MUST NOT use the pipe-to-while pattern that loses counters in a subshell.
        assert "UNIQUE_SLUGS" not in cleanup_tmpl or (
            "UNIQUE_SLUGS" in cleanup_tmpl
            and 'UNIQUE_SLUGS" | while read' not in cleanup_tmpl
        )


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
# Rendered externalwebapp output (generated into a temp project directory)
# ---------------------------------------------------------------------------


def _rendered_cleanup_text(repo_root: Path, tmp_path: Path) -> str:
    proj_dir = tmp_path / "externalwebapp"
    proj_dir.mkdir(parents=True)
    source = repo_root / EPHEMERAL_FILES / "ops/ephemeral-cleanup.sh.tmpl"
    rendered = proj_dir / "ops" / "ephemeral-cleanup.sh"
    rendered.parent.mkdir(parents=True)
    rendered.write_text(
        render_pack_text(
            source.read_text(),
            {"project_name": "externalwebapp", "ephemeral_ttl_hours": "24"},
        )
    )
    return rendered.read_text()


class TestRenderedExternalWebappCleanup:
    """Invariants on the rendered externalwebapp output.

    Rendered project ops files live in scratch/output directories, so these
    assertions render into a temporary directory instead of depending on an
    operator's local generated artifacts.
    """

    @pytest.fixture(scope="class")
    def rendered(
        self,
        repo_root: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> str:
        tmp_path = tmp_path_factory.mktemp("rendered-externalwebapp-cleanup")
        return _rendered_cleanup_text(repo_root, tmp_path)

    def test_no_unrendered_placeholders(self, rendered: str) -> None:
        """Placeholders of the form ``{{snake_case}}`` must all be substituted.

        Note: Docker format strings like ``{{.Repository}}`` are allowed
        because they start with ``.``, not a lowercase letter/underscore.
        """
        import re

        leftovers = re.findall(r"{{[a-z_][a-z0-9_]*}}", rendered)
        assert not leftovers, f"unrendered placeholders: {leftovers}"

    def test_project_name_rendered(self, rendered: str) -> None:
        assert 'PROJECT_NAME="externalwebapp"' in rendered

    def test_ttl_hours_rendered(self, rendered: str) -> None:
        assert 'TTL_HOURS="24"' in rendered

    def test_project_owned_output_has_no_management_header(self, rendered: str) -> None:
        assert "AUTO-GENERATED" not in rendered
        assert "managed" not in rendered.lower()

    def test_rendered_excludes_persistent_app_and_core_projects(
        self,
        rendered: str,
    ) -> None:
        assert "PROTECTED_PROJECT_APP" in rendered
        assert "PROTECTED_PROJECT_CORE" in rendered
        # The protected-set guard is expressed via the shell expansions
        # ``PROTECTED_PROJECT_APP="${PROJECT_NAME}-app"`` /
        # ``PROTECTED_PROJECT_CORE="${PROJECT_NAME}-core"`` rather than
        # literal ``externalwebapp-app`` substrings, so match the suffix shapes.
        assert "PROJECT_NAME}-app" in rendered
        assert "PROJECT_NAME}-core" in rendered

    def test_rendered_uses_filesystem_driven_discovery(self, rendered: str) -> None:
        assert "EPHEMERAL_DIR" in rendered

    def test_rendered_compose_parsing_strips_prefix_exactly(
        self, rendered: str
    ) -> None:
        assert "${_project#${PROJECT_NAME}-}" in rendered

    def test_rendered_volume_parsing_preserves_hyphenated_slugs(
        self, rendered: str
    ) -> None:
        assert "${_volume_rest%%_*}" in rendered
        assert "sed 's/[_-].*//'" not in rendered

    def test_rendered_removes_images_and_volumes(self, rendered: str) -> None:
        assert "docker rmi" in rendered or "docker images" in rendered
        assert "docker volume" in rendered


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

    def test_ephemeral_cleanup_does_not_name_retired_setup_program(
        self, cleanup_tmpl: str
    ) -> None:
        assert "setup-vps-maintenance" not in cleanup_tmpl


class TestProvisionEc2PackSource:
    def test_configures_persistent_swapfile(self, provision_tmpl: str) -> None:
        assert 'SWAPFILE="/swapfile"' in provision_tmpl
        assert 'SWAP_SIZE_MB="1024"' in provision_tmpl
        assert 'mkswap "$SWAPFILE"' in provision_tmpl
        assert 'swapon "$SWAPFILE"' in provision_tmpl
        assert ">> /etc/fstab" in provision_tmpl

    def test_swap_setup_is_idempotent(self, provision_tmpl: str) -> None:
        assert "Swap already active" in provision_tmpl
        assert "Using existing inactive swapfile" in provision_tmpl
        assert "NR > 1" in provision_tmpl
        assert 'grep -Eq "^${SWAPFILE}' in provision_tmpl

    def test_provisioning_leaves_maintenance_policy_to_project(
        self, provision_tmpl: str
    ) -> None:
        assert "selected maintenance and scheduling policy" in provision_tmpl
        assert "setup-vps-maintenance" not in provision_tmpl


# ---------------------------------------------------------------------------
# Workflow integration (teardown + deploy)
# ---------------------------------------------------------------------------


class TestTeardownWorkflow:
    def test_removes_per_slug_images(self, teardown_wf: str) -> None:
        """teardown workflow removes per-slug images."""
        assert "docker rmi" in teardown_wf or "docker images" in teardown_wf

    def test_removes_per_slug_volumes(self, teardown_wf: str) -> None:
        """teardown workflow removes per-slug volumes."""
        assert "docker volume" in teardown_wf


class TestDeployWorkflowCleanupStep:
    def test_cleanup_uses_volumes_flag(self, deploy_wf: str) -> None:
        """deploy workflow cleanup step uses ``--volumes``."""
        assert "--volumes" in deploy_wf

    def test_uses_dangling_only_image_prune(self, deploy_wf: str) -> None:
        """deploy workflow never globally removes tagged cached images."""
        assert "docker image prune -f" in deploy_wf
        assert "docker image prune -af" not in deploy_wf

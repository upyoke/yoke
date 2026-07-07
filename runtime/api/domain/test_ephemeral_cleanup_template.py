"""Structural tests for the ephemeral-cleanup template and related ops surfaces.

port of ``yoke/templates/webapp/ops/tests/test-ephemeral-cleanup-template.sh``
(which was deleted as part of the zero-shell cutover). The original shell
test was a pattern-match audit of the template + rendered buzz output,
covering the cleanup-template invariants:

* ephemeral-cleanup template uses filesystem-driven discovery
* Compose project / volume parsing survives hyphenated slugs
* setup-vps-maintenance installs the cleanup cron entry
* deploy / teardown workflows clean up images and volumes

The Python port preserves the same invariants as regex/substring assertions.
It runs against the ``.sh.tmpl`` template sources and renders a temporary
buzz ops output with the project renderer, so the suite does not depend on
gitignored local artifacts existing in ``projects/buzz/ops``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import project_renderer


def _repo_root() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )


# ---------------------------------------------------------------------------
# Fixtures — load template and optional rendered output text
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def repo_root() -> Path:
    return _repo_root()


@pytest.fixture(scope="module")
def cleanup_tmpl(repo_root: Path) -> str:
    tmpl = repo_root / "templates/webapp/ops/ephemeral-cleanup.sh.tmpl"
    assert tmpl.is_file(), f"template missing: {tmpl}"
    return tmpl.read_text()


@pytest.fixture(scope="module")
def maint_tmpl(repo_root: Path) -> str:
    tmpl = repo_root / "templates/webapp/ops/setup-vps-maintenance.sh.tmpl"
    assert tmpl.is_file(), f"template missing: {tmpl}"
    return tmpl.read_text()


@pytest.fixture(scope="module")
def provision_tmpl(repo_root: Path) -> str:
    tmpl = repo_root / "templates/webapp/ops/provision-ec2.sh.tmpl"
    assert tmpl.is_file(), f"template missing: {tmpl}"
    return tmpl.read_text()


@pytest.fixture(scope="module")
def teardown_wf(repo_root: Path) -> str:
    wf = repo_root / "templates/webapp/ops/ephemeral-teardown.yml"
    assert wf.is_file(), f"workflow template missing: {wf}"
    return wf.read_text()


@pytest.fixture(scope="module")
def deploy_wf(repo_root: Path) -> str:
    wf = repo_root / "templates/webapp/ops/deploy.yml"
    assert wf.is_file(), f"workflow template missing: {wf}"
    return wf.read_text()


# ---------------------------------------------------------------------------
# Template structure (source-of-truth assertions on .sh.tmpl)
# ---------------------------------------------------------------------------

class TestCleanupTemplateShape:
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
        assert '${PROJECT_NAME}-app' in cleanup_tmpl
        assert '${PROJECT_NAME}-core' in cleanup_tmpl
        # Slug-level exclusion applies to both protected projects too.
        assert "grep -v '^app$'" in cleanup_tmpl
        assert "grep -v '^core$'" in cleanup_tmpl

    def test_has_deployment_instructions_header(self, cleanup_tmpl: str) -> None:
        """Header must point the operator at setup-vps-maintenance or the cron line."""
        assert "setup-vps-maintenance" in cleanup_tmpl or "cron" in cleanup_tmpl

    def test_filesystem_driven_discovery(self, cleanup_tmpl: str) -> None:
        """cleanup uses filesystem-driven discovery, not Compose-only."""
        assert "EPHEMERAL_DIR" in cleanup_tmpl

    def test_discovers_slugs_from_directories(self, cleanup_tmpl: str) -> None:
        """slugs are derived from directory basenames."""
        assert "ephemeral" in cleanup_tmpl
        assert "basename" in cleanup_tmpl

    def test_compose_project_parsing_strips_prefix_exactly(self, cleanup_tmpl: str) -> None:
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
        assert "{{ssh_user}}" in cleanup_tmpl or "setup-vps-maintenance" in cleanup_tmpl

    def test_heredoc_pattern_for_while_read(self, cleanup_tmpl: str) -> None:
        """use ``done <<EOF`` so counters survive the while-read loop."""
        assert "done <<EOF" in cleanup_tmpl
        # And MUST NOT use the pipe-to-while pattern that loses counters in a subshell.
        assert "UNIQUE_SLUGS" not in cleanup_tmpl or (
            "UNIQUE_SLUGS" in cleanup_tmpl and "UNIQUE_SLUGS\" | while read" not in cleanup_tmpl
        )


# ---------------------------------------------------------------------------
# Rendered buzz output (generated into a temp project directory)
# ---------------------------------------------------------------------------

def _rendered_cleanup_text(repo_root: Path, tmp_path: Path) -> str:
    proj_dir = tmp_path / "buzz"
    proj_dir.mkdir(parents=True)
    project_renderer.render_ops(
        "buzz",
        {"project_name": "buzz", "ephemeral_ttl_hours": "24"},
        repo_root,
        proj_dir,
        write=True,
    )
    rendered = proj_dir / "ops" / "ephemeral-cleanup.sh"
    assert rendered.is_file(), f"project renderer did not write {rendered}"
    return rendered.read_text()


class TestRenderedBuzzCleanup:
    """Invariants on the rendered buzz output.

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
        tmp_path = tmp_path_factory.mktemp("rendered-buzz-cleanup")
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
        assert 'PROJECT_NAME="buzz"' in rendered

    def test_ttl_hours_rendered(self, rendered: str) -> None:
        assert 'TTL_HOURS="24"' in rendered

    def test_auto_generated_header_references_python_cli(self, rendered: str) -> None:
        """auto-header must name the new Python CLI, not the deleted shell."""
        assert "AUTO-GENERATED by yoke_core.tools.render_project" in rendered
        assert "render-project.sh" not in rendered

    def test_rendered_excludes_persistent_app_and_core_projects(
        self, rendered: str,
    ) -> None:
        assert "PROTECTED_PROJECT_APP" in rendered
        assert "PROTECTED_PROJECT_CORE" in rendered
        # The protected-set guard is expressed via the shell expansions
        # ``PROTECTED_PROJECT_APP="${PROJECT_NAME}-app"`` /
        # ``PROTECTED_PROJECT_CORE="${PROJECT_NAME}-core"`` rather than
        # literal ``buzz-app`` substrings, so match the suffix shapes.
        assert "PROJECT_NAME}-app" in rendered
        assert "PROJECT_NAME}-core" in rendered

    def test_rendered_uses_filesystem_driven_discovery(self, rendered: str) -> None:
        assert "EPHEMERAL_DIR" in rendered

    def test_rendered_compose_parsing_strips_prefix_exactly(self, rendered: str) -> None:
        assert "${_project#${PROJECT_NAME}-}" in rendered

    def test_rendered_volume_parsing_preserves_hyphenated_slugs(self, rendered: str) -> None:
        assert "${_volume_rest%%_*}" in rendered
        assert "sed 's/[_-].*//'" not in rendered

    def test_rendered_removes_images_and_volumes(self, rendered: str) -> None:
        assert "docker rmi" in rendered or "docker images" in rendered
        assert "docker volume" in rendered


# ---------------------------------------------------------------------------
# setup-vps-maintenance template integration
# ---------------------------------------------------------------------------

class TestSetupVpsMaintenanceTemplate:
    def test_installs_cleanup_cron_entry(self, maint_tmpl: str) -> None:
        """maintenance template installs the cleanup cron line."""
        assert "ephemeral-cleanup" in maint_tmpl

    def test_reconciles_stale_entries(self, maint_tmpl: str) -> None:
        """maintenance template reconciles pre-existing cron entries."""
        assert "reconcile" in maint_tmpl

    def test_avoids_local_in_posix_functions(self, maint_tmpl: str) -> None:
        """Yoke POSIX-sh rule: no ``local`` in functions.

        ``local`` is the one accepted deviation repo-wide (per AGENTS.md),
        but the historical shell test explicitly forbade it in this template
        to avoid dash-incompat on the target VPS. Preserve that stricter rule.
        """
        import re
        lines = [ln for ln in maint_tmpl.splitlines() if re.match(r"^\s*local\s", ln)]
        assert not lines, f"found ``local`` declarations in setup-vps-maintenance template: {lines}"


class TestProvisionEc2Template:
    def test_configures_persistent_swapfile(self, provision_tmpl: str) -> None:
        assert 'SWAPFILE="/swapfile"' in provision_tmpl
        assert 'SWAP_SIZE_MB="1024"' in provision_tmpl
        assert "mkswap \"$SWAPFILE\"" in provision_tmpl
        assert "swapon \"$SWAPFILE\"" in provision_tmpl
        assert '>> /etc/fstab' in provision_tmpl

    def test_swap_setup_is_idempotent(self, provision_tmpl: str) -> None:
        assert "Swap already active" in provision_tmpl
        assert "Using existing inactive swapfile" in provision_tmpl
        assert "NR > 1" in provision_tmpl
        assert 'grep -Eq "^${SWAPFILE}' in provision_tmpl


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

    def test_uses_aggressive_image_prune(self, deploy_wf: str) -> None:
        """deploy workflow uses ``docker image prune -af``."""
        assert "docker image prune -af" in deploy_wf

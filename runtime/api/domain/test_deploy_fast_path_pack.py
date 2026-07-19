"""Structural tests for deployment workflow fast-path/cold-fallback invariants."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.domain.pack_render import render_pack_text


PRODUCTION_PACK = "packs/production-deploy/versions/1.0.0/files"
EPHEMERAL_PACK = "packs/ephemeral-environments/versions/1.0.0/files"


def _repo_root() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def _read_pack_source(relative_path: str) -> str:
    return (_repo_root() / relative_path).read_text()


def _production_workflow(name: str) -> str:
    return _read_pack_source(
        f"{PRODUCTION_PACK}/.github/workflows/{{{{project_name}}}}-{name}"
    )


def _ephemeral_workflow(name: str) -> str:
    return _read_pack_source(
        f"{EPHEMERAL_PACK}/.github/workflows/{{{{project_name}}}}-{name}"
    )


def _assert_cached_first_cold_fallback(
    workflow_text: str,
    *,
    build_cmd: str,
) -> None:
    # Fast-path / first-attempt build uses cached layers with no pre-build prune
    # (73469f47b removed `docker builder prune -f --filter "until=6h"` and
    # `docker image prune -f` from the fast-path because pruning before a
    # cache-dependent build is counterproductive).
    assert f"if ! {build_cmd}; then" in workflow_text
    # Cold-start path may clear all build cache, but global image cleanup stays
    # dangling-only so tagged future-release pins on shared hosts survive.
    assert 'docker builder prune -af' in workflow_text
    assert 'docker image prune -f' in workflow_text
    assert f"{build_cmd} --no-cache" in workflow_text


def _assert_maintenance_converges_before_service_mutation(
    workflow_text: str,
) -> None:
    assert "name: Ship Docker maintenance convergence helper" in workflow_text
    assert "ops/docker_maintenance_converge.py" in workflow_text
    assert "name: Converge safe host Docker maintenance" in workflow_text
    assert 'python3 "$HOME/docker_maintenance_converge.py"' in workflow_text
    assert "sudo -n python3" in workflow_text
    assert "--remove-only" in workflow_text
    assert workflow_text.index(
        "Converge safe host Docker maintenance"
    ) < workflow_text.index("Deploy via rsync")


def test_deploy_pack_has_force_rebuild_toggle() -> None:
    deploy_wf = _production_workflow("deploy.yml")
    assert "force_rebuild:" in deploy_wf
    assert "skip fast-path even if production is healthy" in deploy_wf


def test_deploy_pack_keeps_fast_and_cold_paths_distinct() -> None:
    deploy_wf = _production_workflow("deploy.yml")
    assert "name: Rebuild production (fast-path)" in deploy_wf
    _assert_cached_first_cold_fallback(
        deploy_wf,
        build_cmd='docker compose -p {{project_name}}-app build',
    )
    assert 'docker image prune -af' not in deploy_wf
    _assert_maintenance_converges_before_service_mutation(deploy_wf)


def test_deploy_cleanup_runs_after_health_gates() -> None:
    deploy_wf = _production_workflow("deploy.yml")
    assert deploy_wf.index("Wait for web health check") < deploy_wf.index(
        "Reclaim superseded production images"
    )
    assert deploy_wf.index("Check additional smoke paths") < deploy_wf.index(
        "Reclaim superseded production images"
    )
    assert deploy_wf.index("Reclaim superseded production images") < deploy_wf.index(
        "Clean up stale non-production environments"
    )


def test_hotfix_pack_matches_full_cleanup_guarantees() -> None:
    hotfix_wf = _production_workflow("hotfix.yml")
    assert "name: Rebuild production (fast-path)" in hotfix_wf
    _assert_cached_first_cold_fallback(
        hotfix_wf,
        build_cmd='docker compose -p {{project_name}}-app build',
    )
    assert 'docker image prune -af' not in hotfix_wf
    _assert_maintenance_converges_before_service_mutation(hotfix_wf)
    assert "Clean up stale non-production environments" in hotfix_wf
    assert "--volumes" in hotfix_wf
    assert "image_result = subprocess.run(" in hotfix_wf
    assert "volume_result = subprocess.run(" in hotfix_wf
    assert 'subprocess.run([\\"docker\\", \\"volume\\", \\"rm\\", line], check=False)' in hotfix_wf
    assert "shutil.rmtree" in hotfix_wf


def test_hotfix_cleanup_runs_after_health_gates() -> None:
    hotfix_wf = _production_workflow("hotfix.yml")
    assert hotfix_wf.index("Wait for web health check") < hotfix_wf.index(
        "Reclaim superseded production images"
    )
    assert hotfix_wf.index("Check additional smoke paths") < hotfix_wf.index(
        "Reclaim superseded production images"
    )
    assert hotfix_wf.index("Reclaim superseded production images") < hotfix_wf.index(
        "Clean up stale non-production environments"
    )


def test_post_health_image_cleanup_is_retryable_and_fail_visible() -> None:
    for name in ("deploy.yml", "hotfix.yml"):
        workflow = _production_workflow(name)
        cleanup = workflow.split("- name: Reclaim superseded production images", 1)[1]
        cleanup = cleanup.split("- name: Fetch active branch slugs", 1)[0]
        assert "docker image prune --force" in cleanup
        assert "docker image prune --all" not in cleanup
        assert "for attempt in 1 2 3" in cleanup
        assert "Image cleanup failed after 3 attempts" in cleanup
        assert "exit 1" in cleanup


def test_ephemeral_pack_uses_cached_first_cold_fallback() -> None:
    ephemeral_wf = _ephemeral_workflow("ephemeral.yml")
    ephemeral_run_wf = _ephemeral_workflow("ephemeral-run.yml")
    assert "uses: ./.github/workflows/{{project_name}}-ephemeral-run.yml" in ephemeral_wf
    assert "name: Deploy ephemeral environment (full)" in ephemeral_run_wf
    assert "name: Deploy ephemeral environment (fast-path rebuild)" in ephemeral_run_wf
    _assert_cached_first_cold_fallback(
        ephemeral_run_wf,
        build_cmd='docker compose -f docker-compose.ephemeral.yml -p "{{project_name}}-$SLUG" build',
    )
    assert "docker image prune -af" not in ephemeral_run_wf


def test_ephemeral_collision_check_fails_closed_on_ssh_error() -> None:
    ephemeral_run_wf = _ephemeral_workflow("ephemeral-run.yml")

    assert "set -o pipefail" in ephemeral_run_wf
    assert "if collision_output=$(ssh -o LogLevel=ERROR" in ephemeral_run_wf
    assert "Port collision check failed before deployment." in ephemeral_run_wf


def test_rendered_production_lanes_ship_canonical_maintenance_helper(
    tmp_path: Path,
) -> None:
    del tmp_path
    for name in ("deploy.yml", "hotfix.yml"):
        rendered = render_pack_text(
            _production_workflow(name),
            {"project_name": "acme", "PROJECT_NAME_UPPER": "ACME"},
        )
        block = rendered.split(
            "- name: Ship Docker maintenance convergence helper", 1
        )[1].split("- name: Check production readiness", 1)[0]
        assert "ops/docker_maintenance_converge.py" in block
        assert "${{ secrets.ACME_SSH_USER }}" in block
        assert "${{ secrets.ACME_SSH_HOST }}" in block
        assert 'python3 "$HOME/docker_maintenance_converge.py"' in block
        assert "sudo -n python3" in block
        assert "--remove-only" in block
        assert "{{PROJECT_NAME_UPPER}}" not in block

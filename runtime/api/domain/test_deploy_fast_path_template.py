"""Structural tests for deployment workflow fast-path/cold-fallback invariants."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def _read_template(relative_path: str) -> str:
    return (_repo_root() / relative_path).read_text()


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
    # Cold-start path keeps aggressive prune before / after a failed build.
    assert 'docker builder prune -af' in workflow_text
    assert 'docker image prune -af' in workflow_text
    assert f"{build_cmd} --no-cache" in workflow_text


def test_deploy_template_has_force_rebuild_toggle() -> None:
    deploy_wf = _read_template("templates/webapp/ops/deploy.yml")
    assert "force_rebuild:" in deploy_wf
    assert "skip fast-path even if production is healthy" in deploy_wf


def test_deploy_template_keeps_fast_and_cold_paths_distinct() -> None:
    deploy_wf = _read_template("templates/webapp/ops/deploy.yml")
    assert "name: Rebuild production (fast-path)" in deploy_wf
    _assert_cached_first_cold_fallback(
        deploy_wf,
        build_cmd='docker compose -p {{project_name}}-app build',
    )


def test_deploy_cleanup_runs_after_health_gates() -> None:
    deploy_wf = _read_template("templates/webapp/ops/deploy.yml")
    assert deploy_wf.index("Wait for web health check") < deploy_wf.index(
        "Clean up stale non-production environments"
    )
    assert deploy_wf.index("Check additional smoke paths") < deploy_wf.index(
        "Clean up stale non-production environments"
    )


def test_hotfix_template_matches_full_cleanup_guarantees() -> None:
    hotfix_wf = _read_template("templates/webapp/ops/hotfix.yml")
    assert "name: Rebuild production (fast-path)" in hotfix_wf
    _assert_cached_first_cold_fallback(
        hotfix_wf,
        build_cmd='docker compose -p {{project_name}}-app build',
    )
    assert "Clean up stale non-production environments" in hotfix_wf
    assert "--volumes" in hotfix_wf
    assert "image_result = subprocess.run(" in hotfix_wf
    assert "volume_result = subprocess.run(" in hotfix_wf
    assert 'subprocess.run([\\"docker\\", \\"volume\\", \\"rm\\", line], check=False)' in hotfix_wf
    assert "shutil.rmtree" in hotfix_wf


def test_hotfix_cleanup_runs_after_health_gates() -> None:
    hotfix_wf = _read_template("templates/webapp/ops/hotfix.yml")
    assert hotfix_wf.index("Wait for web health check") < hotfix_wf.index(
        "Clean up stale non-production environments"
    )
    assert hotfix_wf.index("Check additional smoke paths") < hotfix_wf.index(
        "Clean up stale non-production environments"
    )


def test_ephemeral_template_uses_cached_first_cold_fallback() -> None:
    ephemeral_wf = _read_template("templates/webapp/ops/ephemeral-deploy.yml")
    ephemeral_run_wf = _read_template("templates/webapp/ops/ephemeral-run.yml")
    assert "uses: ./.github/workflows/{{project_name}}-ephemeral-run.yml" in ephemeral_wf
    assert "name: Deploy ephemeral environment (full)" in ephemeral_run_wf
    assert "name: Deploy ephemeral environment (fast-path rebuild)" in ephemeral_run_wf
    _assert_cached_first_cold_fallback(
        ephemeral_run_wf,
        build_cmd='docker compose -f docker-compose.ephemeral.yml -p "{{project_name}}-$SLUG" build',
    )

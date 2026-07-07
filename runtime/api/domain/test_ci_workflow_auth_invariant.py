"""Guard for the Yoke CI OIDC render-auth posture.

The operator-armed workflows authenticate to AWS via GitHub OIDC
role assumption — static AWS keys and checked-in/read-only DB credentials
must never reappear. The SSH tunnel survives ONLY in the deploy lane
(yoke-env-deploy.yml), whose pipeline needs control-plane DB authority until
deploys no longer require direct control-plane DB access; the DSN is
materialized per run from the RDS-managed secret.
"""

from __future__ import annotations

import re
from pathlib import Path

_INFRA = "yoke-infra.yml"
_CORE_IMAGE = "yoke-core-image.yml"
_ENV_DEPLOY = "yoke-env-deploy.yml"
_DISTRIBUTION_PUBLISH = "yoke-distribution-publish.yml"
_CI_WORKFLOWS = (_INFRA, _CORE_IMAGE, _ENV_DEPLOY, _DISTRIBUTION_PUBLISH)
_PARENTHETICAL_PROVENANCE_TOKEN = re.compile(r"\([A-Z]+\d+[A-Z]*(?:\s|[):])")

# Retired credential surfaces that must stay absent under OIDC auth.
_RETIRED_EVERYWHERE = (
    "YOKE_CI_AWS_ACCESS_KEY_ID",
    "YOKE_CI_AWS_SECRET_ACCESS_KEY",
    "YOKE_CI_RENDER_DSN",
    "YOKE_CI_DEPLOY_DSN",
)

# Deploy-lane-only surfaces: allowed in yoke-env-deploy.yml exclusively.
_DEPLOY_LANE_ONLY = (
    "YOKE_CI_SSH_KEY",
)


def _workflows_dir() -> Path:
    return Path(__file__).resolve().parents[3] / ".github" / "workflows"


def _read(name: str) -> str:
    return _workflows_dir().joinpath(name).read_text()


def test_workflow_comments_describe_current_behavior():
    violations = []
    for name in _CI_WORKFLOWS:
        for lineno, line in enumerate(_read(name).splitlines(), start=1):
            if line.lstrip().startswith("#") and _PARENTHETICAL_PROVENANCE_TOKEN.search(
                line
            ):
                violations.append(f"{name}:{lineno}: {line.strip()}")

    assert not violations, (
        "workflow comments must describe current behavior, not provenance "
        f"tokens: {violations}"
    )


def test_no_retired_credentials_in_any_ci_workflow():
    violations = []
    for name in _CI_WORKFLOWS:
        text = _read(name)
        for needle in _RETIRED_EVERYWHERE:
            if needle in text:
                violations.append(f"{name}: {needle}")
    assert not violations, (
        "retired CI credential surface reappeared (OIDC + the stack-config "
        f"endpoint replaced these): {violations}"
    )


def test_all_ci_workflows_assume_the_oidc_role():
    for name in _CI_WORKFLOWS:
        text = _read(name)
        assert "id-token: write" in text, f"{name} lost the OIDC permission"
        assert "aws-actions/configure-aws-credentials" in text, (
            f"{name} lost the role-assumption step"
        )
        assert "YOKE_CI_ROLE_ARN" in text, (
            f"{name} no longer assumes the repo-variable CI role"
        )


def test_python_workflows_install_split_packages():
    for name in (_INFRA, _ENV_DEPLOY):
        text = _read(name)
        assert "python3 -m pip install -e ." in text
        for package in (
            "packages/yoke-contracts",
            "packages/yoke-cli",
            "packages/yoke-harness",
            "packages/yoke-core",
        ):
            assert f"-e {package}" in text, (
                f"{name} must install split package {package}"
            )

    ci_text = _read("yoke-ci.yml")
    assert "fetch-depth: 0" in ci_text
    assert "cache-dependency-path: uv.lock" in ci_text
    assert "python -m pip install uv" in ci_text
    assert "uv sync --all-packages --all-groups" in ci_text
    assert "uv run python -m pytest runtime/api/ runtime/harness/ tests/" in ci_text
    assert "-n auto" in ci_text


def test_infra_lane_is_db_credential_free():
    text = _read(_INFRA)
    for needle in _DEPLOY_LANE_ONLY:
        assert needle not in text, (
            f"{_INFRA} reacquired {needle}; the render lane consumes "
            "the pulumi-stack-config endpoint, never a DB credential"
        )
    assert "pulumi-stack-config" in text
    assert "YOKE_CI_API_TOKEN" in text
    assert "--settings-file" in text


def test_infra_lane_uses_packaged_tool_modules():
    text = _read(_INFRA)
    assert "python3 -m yoke_core.tools.render_project" in text
    assert "python3 -m yoke_core.tools.pulumi_preview_assert" in text
    assert "runtime.api.tools." not in text


def test_infra_lane_refreshes_pulumi_state_before_updates():
    text = _read(_INFRA)
    assert "pulumi preview --refresh --json" in text
    assert "pulumi up --refresh --yes --non-interactive" in text


def test_infra_workflow_changes_trigger_infra_workflow():
    text = _read(_INFRA)
    assert f'".github/workflows/{_INFRA}"' in text
    assert (
        '"packages/yoke-core/src/yoke_core/domain/github_actions_runner_fleet_capability.py"'
        in text
    )
    assert '"packages/yoke-core/src/yoke_core/domain/project_renderer*.py"' in text


def test_push_deploy_workflows_ignore_docs_only_changes():
    ignored = ('".yoke/strategy/**"', '"docs/**"', '"**/*.md"')
    for name in (_CORE_IMAGE, _ENV_DEPLOY):
        text = _read(name)
        assert "paths-ignore:" in text, (
            f"{name} must not request hosted deploy runners for docs-only pushes"
        )
        for pattern in ignored:
            assert pattern in text, f"{name} missing docs-only ignore {pattern}"


def test_env_deploy_lane_uses_packaged_tool_modules():
    text = _read(_ENV_DEPLOY)
    assert "python3 -m yoke_core.tools.env_autodeploy_gate" in text
    assert "python3 -m yoke_core.cli.db_router" in text
    assert "python3 -m yoke_core.domain.deploy_pipeline" in text
    assert "runtime.api." not in text


def test_env_deploy_lane_labels_release_control_plane_explicitly():
    text = _read(_ENV_DEPLOY)
    assert "YOKE_RELEASE_CONTROL_PLANE_ENV: prod" in text
    assert "release control plane: $YOKE_RELEASE_CONTROL_PLANE_ENV" in text
    assert "target env: $envs" in text
    assert "target_env is stage" in text
    assert "both stage" in text


def test_ci_lane_uses_packaged_readiness_tool():
    text = _read("yoke-ci.yml")
    assert "python -m yoke_core.tools.wait_for_pg" in text
    assert "runtime.api.tools." not in text


def test_ci_python_loader_setup_serializes_host_loader_cache_update():
    text = _read("yoke-ci.yml")
    assert "Register libpython with the system loader cache" in text
    assert "flock /var/lock/yoke-ci-ldconfig.lock" in text
    assert "ldconfig" in text
    assert "sudo ldconfig" not in text
    assert "/etc/ld.so.cache~ temp" in text
    assert "/etc/ld.so.conf.d/yoke-setup-python-${{ matrix.python-version }}.conf" in text
    assert "env -i .venv/bin/python3" in text


def test_distribution_publish_is_deployment_dispatch_target():
    text = _read("yoke-distribution-publish.yml")
    assert "\n  push:" not in text
    assert "workflow_call:" in text
    assert "workflow_dispatch:" in text
    assert 'default: "auto"' in text
    assert "case \"$channel\" in \"\"|auto) channel=\"latest\"" in text
    assert "CI_ROLE_ARN: ${{ vars.YOKE_CI_ROLE_ARN }}" in text
    assert 'role_arn="${PROD_ROLE_ARN:-${LEGACY_ROLE_ARN:-$CI_ROLE_ARN}}"' in text
    assert 'role_arn="${STAGE_ROLE_ARN:-${LEGACY_ROLE_ARN:-$CI_ROLE_ARN}}"' in text
    assert "target_env:" in text
    assert "source_sha:" in text
    assert "git checkout --detach \"$SOURCE_SHA\"" in text
    assert "https://api.upyoke.com" in text
    assert "https://api.stage.upyoke.com" in text
    assert "uv sync --all-packages --all-groups" in text
    assert "python -m yoke_core.tools.build_release" in text
    assert "--output-root" in text
    assert "--output-dir" not in text
    assert "write-channel" not in text
    assert "already exists; refusing immutable overwrite" not in text
    assert "immutable release object differs" in text
    assert "Immutable release objects:" in text
    assert 'aws s3 cp "$CHANNEL_PATH"' in text
    assert "distribution_publish smoke" in text


def test_env_deploy_publishes_stage_distribution_after_release_flow():
    text = _read(_ENV_DEPLOY)

    assert 'YOKE_IMAGE_PREWARM_WAIT_SECONDS: "900"' in text
    assert "waiting for prewarmed image yoke-core:$deploy_image_tag" in text
    assert "outputs:" in text
    assert "deployed: ${{ steps.release_flow.outputs.deployed }}" in text
    assert "id: release_flow" in text
    assert 'echo "deployed=true" >> "$GITHUB_OUTPUT"' in text
    assert "publish-stage-distribution:" in text
    assert "needs: env-deploy" in text
    assert "needs.env-deploy.outputs.deployed == 'true'" in text
    assert "uses: ./.github/workflows/yoke-distribution-publish.yml" in text
    assert "source_sha: ${{ github.sha }}" in text


def test_infra_dispatch_keeps_the_break_glass_dsn_input():
    text = _read(_INFRA)
    assert "render_dsn" in text, (
        "the confirmed-dispatch lane must keep the operator-supplied "
        "render_dsn cold-start break-glass input"
    )


def test_infra_dispatch_can_apply_each_environment_explicitly():
    text = _read(_INFRA)
    assert "confirm_stage_apply" in text
    assert "confirm_prod_apply" in text
    assert "confirm_runner_fleet_apply" in text
    assert "github.event.inputs.confirm_stage_apply == 'yes'" in text
    assert "github.event.inputs.confirm_prod_apply == 'yes'" in text
    assert "github.event.inputs.confirm_runner_fleet_apply == 'yes'" in text
    assert "matrix.stack == 'yoke-stage'" in text
    assert "matrix.stack == 'yoke-prod'" in text
    assert "matrix.stack == 'yoke-runner-fleet'" in text


def test_deploy_lane_tunnel_is_contained_and_documented():
    deploy_text = _read(_ENV_DEPLOY)
    for needle in _DEPLOY_LANE_ONLY:
        assert needle in deploy_text, (
            f"{_ENV_DEPLOY} dropped {needle}; if the deploy lane moved off "
            "the DSN/tunnel transport, update this test + the Pulumi CI "
            "runbook in the operator's private ops repo in the same slice"
        )
    core_text = _read(_CORE_IMAGE)
    for needle in _DEPLOY_LANE_ONLY:
        assert needle not in core_text, (
            f"{_CORE_IMAGE} must stay DB-credential-free: {needle}"
        )
    assert "describe-db-clusters" in deploy_text
    assert "get-secret-value" in deploy_text
    assert "YOKE_PG_DSN_FILE" in deploy_text
    assert "yoke-ci-deploy.dsn" in deploy_text

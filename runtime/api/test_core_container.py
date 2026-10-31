"""Tests for the Yoke core container runtime boundary."""

from __future__ import annotations

import json
import tomllib

import pytest
from packaging.markers import Marker, default_environment
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename
from urllib.parse import urlparse
from pathlib import Path
from unittest import mock

from yoke_core.api import container_healthcheck, server_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_RUNNER_ACTION = REPO_ROOT / ".github" / "actions" / "yoke-test-runner" / "action.yml"


class _Response:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_server_entrypoint_defaults_match_container_contract() -> None:
    settings = server_entrypoint.resolve_settings(argv=[], env={})

    assert settings.app == "yoke_core.api.main:app"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8765
    assert settings.log_level == "info"
    assert settings.workers == 1


def test_server_entrypoint_env_and_flags_resolve_settings() -> None:
    settings = server_entrypoint.resolve_settings(
        argv=["--port", "9000", "--workers", "2"],
        env={
            "YOKE_API_APP": "custom.module:app",
            "YOKE_API_HOST": "127.0.0.1",
            "YOKE_API_LOG_LEVEL": "debug",
        },
    )

    assert settings.app == "custom.module:app"
    assert settings.host == "127.0.0.1"
    assert settings.port == 9000
    assert settings.log_level == "debug"
    assert settings.workers == 2


def test_server_entrypoint_invokes_uvicorn_with_import_string() -> None:
    # This test asserts only the uvicorn invocation shape, so it stubs the
    # bootstrap seams main() runs before serving. Without these stubs, an
    # ambient/leaked DSN (another test's, in the same xdist worker) routes
    # main() into the real birth path and this test picks up that state:
    # universe_is_born gates the first-birth branch, and admin_credential_exists
    # gates the interrupted-birth-completion branch — both must be stubbed so
    # main() falls through to the schema/permission seams and then serves.
    with (
        mock.patch("uvicorn.run") as run,
        mock.patch.object(server_entrypoint, "universe_is_born", return_value=True),
        mock.patch.object(
            server_entrypoint, "admin_credential_exists", return_value=True
        ),
        mock.patch.object(server_entrypoint, "ensure_core_schema"),
        mock.patch.object(server_entrypoint, "ensure_permission_catalog"),
    ):
        rc = server_entrypoint.main(["--host", "127.0.0.1", "--port", "9001"])

    assert rc == 0
    run.assert_called_once_with(
        "yoke_core.api.trusted_proxy:create_app",
        host="127.0.0.1",
        port=9001,
        log_level="info",
        workers=1,
        # Log hygiene: the app emits structured HttpRequestCompleted logs and
        # owns the JSON root handler, so uvicorn's plain-text access log + its
        # own dictConfig are suppressed to keep one CloudWatch JSON stream.
        access_log=False,
        log_config=None,
        factory=True,
        proxy_headers=False,
    )


def test_container_healthcheck_targets_v1_health_by_default() -> None:
    settings = container_healthcheck.resolve_settings(env={})

    assert (
        container_healthcheck.build_url(settings) == "http://127.0.0.1:8765/v1/health"
    )


def test_container_healthcheck_accepts_ok_response() -> None:
    urls: list[tuple[str, float]] = []

    def opener(url: str, timeout: float) -> _Response:
        urls.append((url, timeout))
        return _Response(
            {
                "status": "ok",
                "schema_ready": True,
                "migrations_current": True,
                "migration_content_matches": True,
                "migration_content_evidence_ready": True,
                "migration_content_adoption_required": [],
            }
        )

    settings = container_healthcheck.HealthcheckSettings(
        host="localhost",
        path="v1/health",
        port=8765,
        timeout_seconds=1.5,
    )

    assert container_healthcheck.check_health(settings, opener=opener) == (
        "http://localhost:8765/v1/health"
    )
    assert urls == [("http://localhost:8765/v1/health", 1.5)]


def test_container_healthcheck_rejects_non_ok_response() -> None:
    def opener(url: str, timeout: float) -> _Response:  # noqa: ARG001
        return _Response({"status": "starting"})

    settings = container_healthcheck.resolve_settings(env={})

    try:
        container_healthcheck.check_health(settings, opener=opener)
    except RuntimeError as exc:
        assert "starting" in str(exc)
    else:
        raise AssertionError("healthcheck accepted a non-ok response")


def test_container_healthcheck_rejects_schema_not_ready() -> None:
    def opener(url: str, timeout: float) -> _Response:  # noqa: ARG001
        return _Response(
            {
                "status": "ok",
                "schema_ready": False,
                "schema_missing_tables": ["items"],
            }
        )

    settings = container_healthcheck.resolve_settings(env={})

    try:
        container_healthcheck.check_health(settings, opener=opener)
    except RuntimeError as exc:
        assert "schema_ready=true" in str(exc)
        assert "items" in str(exc)
    else:
        raise AssertionError("healthcheck accepted a DB-not-ready response")


def test_dockerfile_uses_wheel_runtime_and_healthcheck() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG PYTHON_IMAGE=ghcr.io/upyoke/python:3.13-slim" in dockerfile
    assert "FROM ${PYTHON_IMAGE} AS builder" in dockerfile
    assert "FROM ${PYTHON_IMAGE} AS runtime" in dockerfile
    assert "COPY .git_archival.txt ./" in dockerfile
    assert 'ARG YOKE_ENGINE_VERSION=""' in dockerfile
    assert dockerfile.count('ARG YOKE_ENGINE_VERSION=""') == 2
    assert "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CORE" in dockerfile
    assert "YOKE_EXPECTED_ENGINE_VERSION" in dockerfile
    assert "UNRESOLVED_SCM_FALLBACK_VERSION as fallback" in dockerfile
    assert "installed yoke-core version" in dockerfile
    assert "COPY uv.lock ./" in dockerfile
    assert "uv sync --locked --no-default-groups --no-editable" in dockerfile
    assert "COPY --from=builder /opt/yoke-venv /opt/yoke-venv" in dockerfile
    assert "pip install --no-cache-dir" not in dockerfile
    assert "uv build --wheel --package yoke-core" in dockerfile
    assert "wheel_module_completeness.py" in dockerfile
    assert "postgres_binaries.py" in dockerfile
    assert "['ensure_binaries']()" in dockerfile
    assert "libgssapi-krb5-2" in dockerfile
    assert "p._postgres_executable(name), '--version'" in dockerfile
    assert (
        "COPY --chown=yoke:yoke --from=builder /var/lib/yoke/postgres "
        "/var/lib/yoke/postgres"
    ) in dockerfile
    assert 'CMD ["python", "-m", "yoke_core.api.server_entrypoint"]' in dockerfile
    assert "RUN python -m yoke_core.tools.product_wheel_validation" in dockerfile
    assert 'CMD ["python", "-m", "yoke_core.api.container_healthcheck"]' in dockerfile
    assert "EXPOSE 8765" in dockerfile
    assert "USER yoke" in dockerfile
    assert "curl" not in dockerfile
    assert "wget" not in dockerfile


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_locked_runtime_packages_have_cp313_manylinux_wheels(arch: str) -> None:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    packages = {p["name"]: p for p in lock["package"]}
    environment = default_environment() | {
        "sys_platform": "linux", "platform_system": "Linux", "os_name": "posix",
        "platform_machine": arch, "python_version": "3.13",
        "python_full_version": "3.13.0", "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
    }
    pending = [("yoke", ())]
    seen = set()
    runtime = set()
    while pending:
        name, extras = pending.pop()
        if (name, extras) in seen:
            continue
        seen.add((name, extras))
        package = packages[name]
        runtime.add(name)
        dependencies = list(package.get("dependencies", []))
        for extra in extras:
            dependencies.extend(package.get("optional-dependencies", {}).get(extra, []))
        for dependency in dependencies:
            if Marker(dependency.get("marker", "python_version >= '3'")).evaluate(environment):
                pending.append((dependency["name"], tuple(dependency.get("extra", []))))
    platforms = [f"manylinux_2_{minor}_{arch}" for minor in range(5, 42)]
    platforms += [f"manylinux2014_{arch}"]
    if arch == "x86_64":
        platforms += ["manylinux1_x86_64", "manylinux2010_x86_64"]
    tags = set(cpython_tags((3, 13), platforms=platforms))
    tags.update(compatible_tags((3, 13), interpreter="cp313", platforms=platforms))
    missing = []
    for name in sorted(runtime):
        package = packages[name]
        if "registry" not in package["source"]:
            continue
        wheels = [parse_wheel_filename(Path(urlparse(w["url"]).path).name)[3]
                  for w in package.get("wheels", [])]
        if not any(tags & wheel_tags for wheel_tags in wheels):
            missing.append(f"{name}=={package['version']}")
    assert not missing, f"cp313 {arch} wheels missing in uv.lock: {missing}"


def test_git_archive_metadata_is_exported_for_image_wheel_versions() -> None:
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    archival = (REPO_ROOT / ".git_archival.txt").read_text(encoding="utf-8")

    assert ".git_archival.txt export-subst" in attributes
    assert "node: $Format:%H$" in archival
    assert "describe-name: $Format:%(describe:tags=true,match=*[0-9]*)$" in archival
    assert "ref-names: $Format:%D$" in archival


def test_dockerfile_serves_the_installed_packaged_tree() -> None:
    """Install-bundle and Pack routes read the wheel's packaged tree.

    The image declares no ``YOKE_SERVER_TREE_ROOT`` and copies no second
    source tree, so ``server_tree_root()`` resolves the installed snapshot
    whose bundles carry this image's build as ``source_build``.
    """
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "YOKE_SERVER_TREE_ROOT" not in dockerfile
    assert "/srv/yoke-tree" not in dockerfile
    assert "YOKE_BUILD_SHA=${YOKE_BUILD_SHA}" in dockerfile


def test_dockerignore_keeps_legacy_local_shapes_out_of_build_context() -> None:
    ignored = set(
        (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )

    assert ".worktrees" in ignored
    assert "data/" in ignored
    assert "projects/" in ignored


def test_ci_builds_container_without_registry_push() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml").read_text(
        encoding="utf-8"
    )

    assert "docker build" in workflow
    assert "fetch-depth: 0" in workflow
    assert "python -m setuptools_scm --root" in workflow
    assert '--build-arg "YOKE_ENGINE_VERSION=$YOKE_ENGINE_VERSION"' in workflow
    assert "docker push" not in workflow


def test_ci_workflow_preserves_pipe_failures() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml").read_text(
        encoding="utf-8"
    )
    # Shard setup, Postgres included, lives in the shared runner action.
    action = TEST_RUNNER_ACTION.read_text(encoding="utf-8")

    assert "./.github/actions/yoke-test-runner" in workflow
    assert "set -o pipefail\n        host_port=" in action
    assert "Postgres host port did not resolve" in action
    # The shard's own exit-code fidelity moved to yoke_core.tools.ci_shards,
    # which returns pytest's code directly instead of through a pipeline.
    assert "2>&1 | tee" not in workflow
    assert "PIPESTATUS" not in workflow


def test_ci_shards_backend_suite_without_aggregate_tail() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml").read_text(
        encoding="utf-8"
    )

    assert "test_shard:" in workflow
    # The fan-out and the split it selects come from one module, so the
    # workflow names neither the shard list nor the split count.
    assert "shard: ${{ fromJSON(needs.repo_contracts.outputs.shards) }}" in workflow
    assert "yoke_core.tools.ci_shards fan-out" in workflow
    assert '--group "${{ matrix.shard }}"' in workflow
    assert "needs: test_shard" not in workflow
    assert "SHARD_RESULT" not in workflow
    assert "\n  test:\n" not in workflow
    assert "  container:" in workflow
    container = workflow.split("  container:", 1)[1]
    # The image build stamps the commit's version; coverage reuse never skips it.
    assert "needs:" not in container
    assert "needs: test_shard" not in container


def test_ci_disk_reclaim_receives_explicit_runner_authority() -> None:
    workflow = TEST_RUNNER_ACTION.read_text(encoding="utf-8")

    assert '--runner-environment "${{ runner.environment }}"' in workflow
    assert '--runner-os "${{ runner.os }}"' in workflow
    assert "--hosted-image-build-cleanup" not in workflow

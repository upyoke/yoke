"""Tests for the Yoke core container runtime boundary."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest import mock

from yoke_core.api import container_healthcheck, server_entrypoint
from yoke_core.tools.local_wheel_constraints import constraints_for_wheelhouse


REPO_ROOT = Path(__file__).resolve().parents[2]


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
    with mock.patch("uvicorn.run") as run, mock.patch.object(
        server_entrypoint, "universe_is_born", return_value=True
    ), mock.patch.object(
        server_entrypoint, "admin_credential_exists", return_value=True
    ), mock.patch.object(
        server_entrypoint, "ensure_core_schema"
    ), mock.patch.object(
        server_entrypoint, "ensure_permission_catalog"
    ):
        rc = server_entrypoint.main(["--host", "127.0.0.1", "--port", "9001"])

    assert rc == 0
    run.assert_called_once_with(
        "yoke_core.api.main:app",
        host="127.0.0.1",
        port=9001,
        log_level="info",
        workers=1,
        # Log hygiene: the app emits structured HttpRequestCompleted logs and
        # owns the JSON root handler, so uvicorn's plain-text access log + its
        # own dictConfig are suppressed to keep one CloudWatch JSON stream.
        access_log=False,
        log_config=None,
    )


def test_container_healthcheck_targets_v1_health_by_default() -> None:
    settings = container_healthcheck.resolve_settings(env={})

    assert (
        container_healthcheck.build_url(settings)
        == "http://127.0.0.1:8765/v1/health"
    )


def test_container_healthcheck_accepts_ok_response() -> None:
    urls: list[tuple[str, float]] = []

    def opener(url: str, timeout: float) -> _Response:
        urls.append((url, timeout))
        return _Response({"status": "ok", "schema_ready": True})

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
        return _Response({
            "status": "ok",
            "schema_ready": False,
            "schema_missing_tables": ["items"],
        })

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

    assert "FROM python:3.13-slim AS builder" in dockerfile
    assert "FROM python:3.13-slim AS runtime" in dockerfile
    assert "COPY .git_archival.txt ./" in dockerfile
    assert 'ARG YOKE_ENGINE_VERSION=""' in dockerfile
    assert dockerfile.count('ARG YOKE_ENGINE_VERSION=""') == 2
    assert "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CORE" in dockerfile
    assert "YOKE_EXPECTED_ENGINE_VERSION" in dockerfile
    assert "UNRESOLVED_SCM_FALLBACK_VERSION as fallback" in dockerfile
    assert "installed yoke-core version" in dockerfile
    assert (
        "python -m pip wheel --no-deps --wheel-dir /wheels "
        "./packages/yoke-harness" in dockerfile
    )
    assert "local_wheel_constraints.py" in dockerfile
    assert "postgres_binaries.py" in dockerfile
    assert "['ensure_binaries']()" in dockerfile
    assert "libgssapi-krb5-2" in dockerfile
    assert "p._postgres_executable(name), '--version'" in dockerfile
    assert (
        "COPY --chown=yoke:yoke --from=builder /var/lib/yoke/postgres "
        "/var/lib/yoke/postgres"
    ) in dockerfile
    assert "--constraint /tmp/yoke-local-constraints.txt ." in dockerfile
    assert dockerfile.index("local_wheel_constraints.py") < dockerfile.index(
        "--constraint /tmp/yoke-local-constraints.txt ."
    )
    assert 'CMD ["python", "-m", "yoke_core.api.server_entrypoint"]' in dockerfile
    assert (
        'CMD ["python", "-m", "yoke_core.api.container_healthcheck"]'
        in dockerfile
    )
    assert "EXPOSE 8765" in dockerfile
    assert "USER yoke" in dockerfile
    assert "curl" not in dockerfile
    assert "wget" not in dockerfile


def test_local_wheel_constraints_emit_exact_split_package_versions(
    tmp_path: Path,
) -> None:
    _write_wheel_metadata(
        tmp_path / "yoke_harness-0.2.0.dev1-py3-none-any.whl",
        name="yoke-harness",
        version="0.2.0.dev1",
    )
    _write_wheel_metadata(
        tmp_path / "yoke_cli-0.2.0.dev1-py3-none-any.whl",
        name="yoke-cli",
        version="0.2.0.dev1",
    )

    assert constraints_for_wheelhouse(
        tmp_path, ["yoke-cli", "yoke-harness"]
    ) == [
        "yoke-cli==0.2.0.dev1",
        "yoke-harness==0.2.0.dev1",
    ]


def _write_wheel_metadata(path: Path, *, name: str, version: str) -> None:
    dist_info = path.name.split("-py3-", 1)[0] + ".dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n",
        )


def test_git_archive_metadata_is_exported_for_image_wheel_versions() -> None:
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    archival = (REPO_ROOT / ".git_archival.txt").read_text(encoding="utf-8")

    assert ".git_archival.txt export-subst" in attributes
    assert "node: $Format:%H$" in archival
    assert "describe-name: $Format:%(describe:tags=true,match=*[0-9]*)$" in archival
    assert "ref-names: $Format:%D$" in archival


def test_dockerfile_ships_declared_server_tree_bundle_sources() -> None:
    """Pack and agent routes read repo-root sources the wheel cannot carry.

    Install-bundle and Pack routes resolve skills/Packs/adapters
    from ``server_tree_root()``; in the container that root is the
    declared ``YOKE_SERVER_TREE_ROOT`` tree, COPYed with repo layout.
    """
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "YOKE_SERVER_TREE_ROOT=/srv/yoke-tree" in dockerfile
    assert "COPY packs /srv/yoke-tree/packs" in dockerfile
    assert "COPY .agents /srv/yoke-tree/.agents" in dockerfile
    assert (
        "COPY runtime/harness/claude/agents "
        "/srv/yoke-tree/runtime/harness/claude/agents" in dockerfile
    )
    assert (
        "COPY runtime/harness/claude/rules "
        "/srv/yoke-tree/runtime/harness/claude/rules" in dockerfile
    )
    assert (
        "COPY runtime/harness/codex/agents "
        "/srv/yoke-tree/runtime/harness/codex/agents" in dockerfile
    )


def test_dockerignore_keeps_legacy_local_shapes_out_of_build_context() -> None:
    ignored = set(
        (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )

    assert ".worktrees" in ignored
    assert "data/" in ignored
    assert "projects/" in ignored


def test_ci_builds_container_without_registry_push() -> None:
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"
    ).read_text(encoding="utf-8")

    assert "docker build" in workflow
    assert "fetch-depth: 0" in workflow
    assert "python -m setuptools_scm --root" in workflow
    assert '--build-arg "YOKE_ENGINE_VERSION=$YOKE_ENGINE_VERSION"' in workflow
    assert "docker push" not in workflow


def test_ci_workflow_preserves_pipe_failures() -> None:
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"
    ).read_text(encoding="utf-8")

    assert "set -o pipefail\n          host_port=" in workflow
    assert "Postgres host port did not resolve" in workflow
    assert "2>&1 | tee pytest-output.txt" in workflow
    assert 'exit "${PIPESTATUS[0]}"' in workflow


def test_ci_shards_backend_suite_without_renaming_required_checks() -> None:
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"
    ).read_text(encoding="utf-8")

    assert "test_shard:" in workflow
    assert "shard: [1, 2, 3, 4]" in workflow
    assert "--splits 4" in workflow
    assert '--group "${{ matrix.shard }}"' in workflow
    assert "--splitting-algorithm least_duration" in workflow
    assert "--dist worksteal" in workflow
    assert "test:\n    name: test\n    needs: test_shard" in workflow
    container = workflow.split("  container:", 1)[1]
    assert "needs: test" not in container


def test_ci_disk_reclaim_receives_explicit_runner_authority() -> None:
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"
    ).read_text(encoding="utf-8")

    assert '--runner-environment "${{ runner.environment }}"' in workflow
    assert '--runner-os "${{ runner.os }}"' in workflow
    assert "--hosted-image-build-cleanup" not in workflow

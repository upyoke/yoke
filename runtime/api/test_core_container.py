"""Tests for the Yoke core container runtime boundary."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from yoke_core.api import container_healthcheck, server_entrypoint


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
    assert (
        "python -m pip wheel --wheel-dir /wheels --find-links /wheels ."
        in dockerfile
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


def test_dockerfile_ships_declared_server_tree_bundle_sources() -> None:
    """Bundle routes read repo-root sources the wheel cannot carry.

    install-bundle and template routes resolve skills/templates/adapters
    from ``server_tree_root()``; in the container that root is the
    declared ``YOKE_SERVER_TREE_ROOT`` tree, COPYed with repo layout.
    Live regression: prod 500 on ``GET /v1/templates`` because the image
    carried only the wheel (field-note evidence, run-20260611-003).
    """
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "YOKE_SERVER_TREE_ROOT=/srv/yoke-tree" in dockerfile
    assert "COPY templates /srv/yoke-tree/templates" in dockerfile
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
    assert "docker push" not in workflow

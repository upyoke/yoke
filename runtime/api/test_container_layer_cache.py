"""Container caching preserves dependency reuse and every product gate."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_uses_wheel_runtime_and_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG PYTHON_IMAGE=ghcr.io/upyoke/python:3.13-slim" in dockerfile
    assert "FROM runtime-base AS builder" in dockerfile
    assert "FROM ${PYTHON_IMAGE} AS runtime-base" in dockerfile
    assert "FROM runtime-base AS runtime" in dockerfile
    assert "--mount=type=bind,source=.,target=/build,rw" in dockerfile
    assert 'ARG YOKE_ENGINE_VERSION=""' in dockerfile
    assert dockerfile.count('ARG YOKE_ENGINE_VERSION=""') == 2
    assert "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CORE" in dockerfile
    assert "YOKE_EXPECTED_ENGINE_VERSION" in dockerfile
    assert "UNRESOLVED_SCM_FALLBACK_VERSION as fallback" in dockerfile
    assert "installed yoke-core version" in dockerfile
    assert "COPY uv.lock ./" in dockerfile
    assert "uv sync --locked --no-default-groups --no-editable" in dockerfile
    assert "UV_PROJECT_ENVIRONMENT=/opt/yoke-venv" in dockerfile
    assert "pip install --no-cache-dir" not in dockerfile
    assert "uv build --wheel --all-packages" in dockerfile
    assert "wheel_module_completeness.py" in dockerfile
    assert "postgres_binaries.py" in dockerfile
    assert "['ensure_binaries']()" in dockerfile
    assert "YOKE_PG_BIN_DIR=/opt/yoke-postgres/bin" in dockerfile
    assert "RUN YOKE_MACHINE_HOME=/var/lib/yoke/.yoke python" in dockerfile
    assert "libgssapi-krb5-2" in dockerfile
    assert "p._postgres_executable(name), '--version'" in dockerfile
    assert ("shutil.move(str(binaries.parent), '/opt/yoke-postgres')") in dockerfile
    assert 'CMD ["python", "-m", "yoke_core.api.server_entrypoint"]' in dockerfile
    assert "RUN python -m yoke_core.tools.product_wheel_validation" in dockerfile
    assert 'CMD ["python", "-m", "yoke_core.api.container_healthcheck"]' in dockerfile
    assert "EXPOSE 8765" in dockerfile
    assert "USER yoke" in dockerfile
    assert "curl" not in dockerfile
    assert "wget" not in dockerfile


def test_dependency_inputs_exclude_source_and_release_identity():
    dockerfile = (ROOT / "Dockerfile").read_text()
    dependencies, builder = dockerfile.split("FROM runtime-base AS builder", 1)
    assert "--no-install-workspace" in dependencies
    assert "--locked --no-default-groups" in dependencies
    assert "COPY runtime" not in dependencies
    assert "COPY packages ./packages" not in dependencies
    assert "ARG YOKE_ENGINE_VERSION" not in dependencies
    for manifest in (ROOT / "packages").glob("yoke-*/pyproject.toml"):
        assert f"COPY {manifest.relative_to(ROOT)} " in dependencies
    assert builder.count("uv build --wheel --all-packages") == 1
    runtime = builder.split("FROM runtime-base AS runtime", 1)[1]
    identity = runtime.index('ARG YOKE_BUILD_SHA=""')
    assert runtime.index("uv pip install") < identity
    assert "--no-deps --no-index /wheels/*.whl" in runtime
    assert "--compile-bytecode" in dependencies
    assert "--no-cache --compile-bytecode" in runtime
    for stable in ("apt-get update", "addgroup", "uv sync", "['ensure_binaries']()"):
        assert stable in dependencies
        assert stable not in runtime
    assert "YOKE_MACHINE_HOME=/tmp/postgres-bootstrap" in dependencies
    assert "COPY packages ./packages" not in builder
    assert "COPY runtime ./runtime" not in builder
    assert "--mount=type=bind,source=.,target=/build,rw" in builder
    assert "uv build --wheel --all-packages --out-dir /wheels" in builder
    assert "source=/wheels,target=/wheels" in runtime
    assert "--mount=type=bind,from=tools" in dependencies
    assert "--mount=type=bind,from=tools" in runtime


@pytest.mark.parametrize("wheel,bundle", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_parallel_validation_requires_both_processes_to_succeed(
    tmp_path, wheel, bundle
):
    python = tmp_path / "python"
    python.write_text(
        "#!/bin/sh\n"
        'echo "$*" >> "$CALLS"\n'
        'case "$*" in\n'
        '  *product_wheel_validation*) exit "$WHEEL_STATUS";;\n'
        '  *container_bundle_validation*) exit "$BUNDLE_STATUS";;\n'
        "  *) exit 99;;\n"
        "esac\n"
    )
    python.chmod(0o755)
    dockerfile = (ROOT / "Dockerfile").read_text()
    command = dockerfile.split(
        "RUN python -m yoke_core.tools.product_wheel_validation", 1
    )[1].split("\n\n", 1)[0]
    command = "python -m yoke_core.tools.product_wheel_validation" + command
    result = subprocess.run(
        ["sh", "-c", command.replace("\\\n", "")],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "WHEEL_STATUS": str(wheel),
            "BUNDLE_STATUS": str(bundle),
            "CALLS": str(tmp_path / "calls"),
        },
        capture_output=True,
    )
    assert (result.returncode == 0) == (wheel == 0 and bundle == 0)
    calls = (tmp_path / "calls").read_text().splitlines()
    assert sorted(calls) == sorted(
        [
            "-m yoke_core.tools.product_wheel_validation",
            "-m yoke_core.tools.container_bundle_validation verify",
        ]
    )

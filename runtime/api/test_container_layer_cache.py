"""Container caching preserves dependency reuse and every product gate."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_uses_wheel_runtime_and_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG PYTHON_IMAGE=ghcr.io/upyoke/python:3.13-slim" in dockerfile
    assert "FROM tools AS builder" in dockerfile
    assert "FROM ${PYTHON_IMAGE} AS runtime-base" in dockerfile
    assert "FROM runtime-base AS runtime" in dockerfile
    assert "--mount=type=bind,source=packages,target=/build/packages,rw" in dockerfile
    assert 'ARG YOKE_ENGINE_VERSION=""' in dockerfile
    assert dockerfile.count('ARG YOKE_ENGINE_VERSION=""') == 2
    assert "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CORE" in dockerfile
    assert "YOKE_EXPECTED_ENGINE_VERSION" in dockerfile
    assert "UNRESOLVED_SCM_FALLBACK_VERSION as fallback" in dockerfile
    assert "installed yoke-core version" in dockerfile
    assert "COPY uv.lock ./" in dockerfile
    assert "uv sync --locked --no-default-groups --no-editable" in dockerfile
    assert "UV_PROJECT_ENVIRONMENT=/opt/yoke-venv" in dockerfile
    assert "pip install --no-cache-dir uv==0.12.1" in dockerfile
    assert 'uv build --wheel --package "$package"' in dockerfile
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
    dependencies, builder = dockerfile.split("FROM tools AS builder", 1)
    assert "--no-install-workspace" in dependencies
    assert "--locked --no-default-groups" in dependencies
    assert "COPY runtime" not in dependencies
    assert "COPY packages ./packages" not in dependencies
    assert "ARG YOKE_ENGINE_VERSION" not in dependencies
    for manifest in (ROOT / "packages").glob("yoke-*/pyproject.toml"):
        assert f"COPY {manifest.relative_to(ROOT)} " in dependencies
    assert builder.count("uv build --wheel --package") == 1
    assert "--all-packages" not in builder
    for package in ("contracts", "cli", "harness", "core"):
        assert f"yoke-{package}" in builder
    assert "source=runtime" not in builder
    assert "source=.git_archival.txt,target=/build/.git_archival.txt" in builder
    assert "server image contains development runtime package" in builder
    runtime = builder.split("FROM runtime-base AS runtime", 1)[1]
    identity = runtime.index('ARG YOKE_BUILD_SHA=""')
    assert runtime.index("uv pip install") < identity
    assert "--no-deps --no-index /wheels/*.whl" in runtime
    assert "--compile-bytecode --no-cache" in dependencies
    assert "--no-cache --compile-bytecode" in runtime
    for stable in ("apt-get update", "addgroup", "uv sync", "['ensure_binaries']()"):
        assert stable in dependencies
        assert stable not in runtime
    assert "YOKE_MACHINE_HOME=/tmp/postgres-bootstrap" in dependencies
    assert "chown -R yoke:yoke /opt/yoke-postgres" in dependencies
    assert "COPY packages ./packages" not in builder
    assert "COPY runtime ./runtime" not in builder
    assert "--mount=type=bind,source=packages,target=/build/packages,rw" in builder
    assert "UV_CACHE_DIR=/build/packages/.uv-build-cache" in builder
    assert "source=/wheels,target=/wheels" in runtime
    assert "--mount=type=bind,from=tools" in dependencies
    assert "uv venv /opt/yoke-build-env" in dependencies
    assert "--no-build-isolation --offline" in builder
    assert "--python /opt/yoke-build-env/bin/python" in builder
    assert "FROM runtime-base AS builder" not in dockerfile
    assert "--mount=type=bind,from=tools" in runtime


def test_cached_backend_install_uses_every_declared_build_requirement(monkeypatch):
    import re
    import tomllib

    dockerfile = (ROOT / "Dockerfile").read_text()
    tools = dockerfile.split("FROM ${PYTHON_IMAGE} AS runtime-base", 1)[0]
    command = re.search(
        r'python -c "(import pathlib, subprocess, tomllib;[^\n]+)"', tools
    )
    assert command is not None
    expected = set()
    for manifest in (ROOT / "packages").glob("yoke-*/pyproject.toml"):
        assert f"COPY {manifest.relative_to(ROOT)} " in tools
        expected.update(tomllib.loads(manifest.read_text())["build-system"]["requires"])
    calls = []
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )
    exec(command.group(1), {})
    assert calls == [
        (
            [
                "uv",
                "pip",
                "install",
                "--python",
                "/opt/yoke-build-env/bin/python",
                "--no-cache",
                *sorted(expected),
            ],
            {"check": True},
        )
    ]


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


@pytest.mark.parametrize("failed_package", ["", "yoke-cli", "yoke-core"])
def test_product_builds_run_concurrently_and_wait_for_every_result(
    tmp_path, failed_package
):
    import sys

    uv = tmp_path / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys, time\n"
        "root = pathlib.Path(os.environ['CALLS'])\n"
        "package = sys.argv[4]\n"
        "(root / package).touch()\n"
        "deadline = time.monotonic() + 3\n"
        "while len(list(root.iterdir())) < 4:\n"
        "    if time.monotonic() > deadline: sys.exit(90)\n"
        "    time.sleep(0.01)\n"
        "(root.parent / ('finished-' + package)).touch()\n"
        "sys.exit(package == os.environ['FAILED_PACKAGE'])\n"
    )
    uv.chmod(0o755)
    calls = tmp_path / "calls"
    calls.mkdir()
    command = 'pids="";' + (ROOT / "Dockerfile").read_text().split('pids="";', 1)[1]
    command = command.split("&& python packages/", 1)[0]
    result = subprocess.run(
        ["sh", "-c", command.replace("\\\n", "")],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "CALLS": str(calls),
            "FAILED_PACKAGE": failed_package,
        },
        capture_output=True,
        timeout=10,
    )
    products = {"yoke-contracts", "yoke-cli", "yoke-harness", "yoke-core"}
    assert {p.name for p in calls.iterdir()} == products
    assert {
        p.name.removeprefix("finished-") for p in tmp_path.glob("finished-*")
    } == products
    assert (result.returncode == 0) == (not failed_package)

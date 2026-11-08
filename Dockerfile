# No `# syntax=` frontend pin: this file uses only builtin-frontend features,
# and an external frontend directive makes every build fetch that image from
# Docker Hub first — one more registry round-trip that can fail the whole
# build on a transient network error before any real work starts.

# Public GHCR copy of the official image, refreshed by ci-image-mirror.
# One ARG so both stages pull the same image without upstream registry quotas.
ARG PYTHON_IMAGE=ghcr.io/upyoke/python:3.13-slim

FROM ${PYTHON_IMAGE} AS tools
RUN python -m pip install --no-cache-dir uv==0.12.1
WORKDIR /build
COPY packages/yoke-core/pyproject.toml ./packages/yoke-core/pyproject.toml
COPY packages/yoke-cli/pyproject.toml ./packages/yoke-cli/pyproject.toml
COPY packages/yoke-contracts/pyproject.toml ./packages/yoke-contracts/pyproject.toml
COPY packages/yoke-harness/pyproject.toml ./packages/yoke-harness/pyproject.toml
# Build backends have the same exact versions as the product manifests. Cache
# their isolated environment once, without adding build tools to the runtime.
RUN uv venv /opt/yoke-build-env \
    && python -c "import pathlib, subprocess, tomllib; requirements = sorted({r for p in pathlib.Path('packages').glob('*/pyproject.toml') for r in tomllib.loads(p.read_text())['build-system']['requires']}); subprocess.run(['uv', 'pip', 'install', '--python', '/opt/yoke-build-env/bin/python', '--no-cache', *requirements], check=True)"

FROM ${PYTHON_IMAGE} AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOKE_API_HOST=0.0.0.0 \
    YOKE_API_PORT=8765 \
    YOKE_MACHINE_HOME=/var/lib/yoke \
    YOKE_PG_BIN_DIR=/opt/yoke-postgres/bin \
    PATH=/opt/yoke-venv/bin:$PATH

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system yoke \
    && adduser --system --ingroup yoke --home /var/lib/yoke yoke \
    && mkdir -p /var/lib/yoke/.yoke \
    && chown -R yoke:yoke /var/lib/yoke

# Only the transitive bootstrap sources own this layer. Workspace manifests,
# unrelated client modules and release clocks cannot trigger a new download.
RUN --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/__init__.py,target=/bootstrap/contracts/yoke_contracts/__init__.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/api_urls.py,target=/bootstrap/contracts/yoke_contracts/api_urls.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/git_ref_name.py,target=/bootstrap/contracts/yoke_contracts/git_ref_name.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/github_app_snapshot.py,target=/bootstrap/contracts/yoke_contracts/github_app_snapshot.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/github_app_tokens.py,target=/bootstrap/contracts/yoke_contracts/github_app_tokens.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/github_origin.py,target=/bootstrap/contracts/yoke_contracts/github_origin.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/github_web_endpoint.py,target=/bootstrap/contracts/yoke_contracts/github_web_endpoint.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/__init__.py,target=/bootstrap/contracts/yoke_contracts/machine_config/__init__.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/checkout.py,target=/bootstrap/contracts/yoke_contracts/machine_config/checkout.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/credential_sources.py,target=/bootstrap/contracts/yoke_contracts/machine_config/credential_sources.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/directories.py,target=/bootstrap/contracts/yoke_contracts/machine_config/directories.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/paths.py,target=/bootstrap/contracts/yoke_contracts/machine_config/paths.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/retired_keys.py,target=/bootstrap/contracts/yoke_contracts/machine_config/retired_keys.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/runtime.py,target=/bootstrap/contracts/yoke_contracts/machine_config/runtime.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_connection_validation.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_connection_validation.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_connections.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_connections.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_example.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_example.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_github.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_github.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_github_access.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_github_access.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_product.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_product.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_project_validation.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_project_validation.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_projects.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_projects.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/schema_transport.py,target=/bootstrap/contracts/yoke_contracts/machine_config/schema_transport.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/selection.py,target=/bootstrap/contracts/yoke_contracts/machine_config/selection.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/machine_config/unknown_keys.py,target=/bootstrap/contracts/yoke_contracts/machine_config/unknown_keys.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/platform_file_lock.py,target=/bootstrap/contracts/yoke_contracts/platform_file_lock.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/resilient_fetch.py,target=/bootstrap/contracts/yoke_contracts/resilient_fetch.py \
    --mount=type=bind,source=packages/yoke-contracts/src/yoke_contracts/terminal_detached_process.py,target=/bootstrap/contracts/yoke_contracts/terminal_detached_process.py \
    --mount=type=bind,source=packages/yoke-core/src/yoke_core/domain/postgres_binaries.py,target=/bootstrap/postgres_binaries.py \
    PYTHONPATH=/bootstrap/contracts YOKE_MACHINE_HOME=/tmp/postgres-bootstrap \
    python -c "import runpy, shutil; binaries = runpy.run_path('/bootstrap/postgres_binaries.py')['ensure_binaries'](); shutil.move(str(binaries.parent), '/opt/yoke-postgres'); shutil.rmtree('/tmp/postgres-bootstrap')" \
    && chown -R yoke:yoke /opt/yoke-postgres

# Lockfile and manifests alone own third-party dependencies. Workspace source
# and release clocks must not rebuild or republish this large virtualenv.
ENV UV_PROJECT_ENVIRONMENT=/opt/yoke-venv
COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/yoke-core/pyproject.toml ./packages/yoke-core/pyproject.toml
COPY packages/yoke-cli/pyproject.toml ./packages/yoke-cli/pyproject.toml
COPY packages/yoke-contracts/pyproject.toml ./packages/yoke-contracts/pyproject.toml
COPY packages/yoke-harness/pyproject.toml ./packages/yoke-harness/pyproject.toml
RUN --mount=type=bind,from=tools,source=/usr/local/bin/uv,target=/usr/local/bin/uv \
    uv sync --locked --no-default-groups --no-editable --no-install-workspace --compile-bytecode --no-cache

FROM tools AS builder

WORKDIR /build

# Wheel production can run alongside runtime layer downloads. Each backend
# writes into its own package directory in the discarded source bind mount.
# The whole context is mounted because yoke-core's setup.py builds the
# install-bundle tree from repo-root sources (docs, skills, packs, harness).
ARG YOKE_ENGINE_VERSION=""

RUN --mount=type=bind,target=/build,rw \
    if [ -n "$YOKE_ENGINE_VERSION" ]; then \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CONTRACTS="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CLI="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_HARNESS="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CORE="$YOKE_ENGINE_VERSION"; \
    fi; \
    pids=""; \
    for package in yoke-contracts yoke-cli yoke-harness yoke-core; do \
        UV_CACHE_DIR=/build/packages/.uv-build-cache \
        uv build --wheel --package "$package" --out-dir /wheels \
            --python /opt/yoke-build-env/bin/python --no-build-isolation --offline \
            --config-setting=--build-option=--compression=stored & \
        pids="$pids $!"; \
    done; \
    status=0; \
    for pid in $pids; do wait "$pid" || status=1; done; \
    test "$status" -eq 0 \
    && python packages/yoke-core/src/yoke_core/tools/wheel_module_completeness.py \
        --package-root packages/yoke-core/src/yoke_core \
        --wheel /wheels/yoke_core-*.whl

FROM runtime-base AS runtime

WORKDIR /app

# Bind mounts keep build tooling/wheels out of the image. Only the small
# workspace installation changes; the external-dependency layer stays shared.
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    --mount=type=bind,from=tools,source=/usr/local/bin/uv,target=/usr/local/bin/uv \
    uv pip install --python /opt/yoke-venv/bin/python --no-cache --compile-bytecode --no-deps --no-index /wheels/*.whl

# Commit identity belongs after stable OS, user, PostgreSQL and dependencies.
ARG YOKE_BUILD_SHA=""
ARG YOKE_ENGINE_VERSION=""
ENV YOKE_BUILD_SHA=${YOKE_BUILD_SHA}

# Import every installed core module with the source checkout absent.
# This deliberately runs after source and wheels have left the runtime stage.
# The installed wheel's packaged tree is the server tree: install-bundle and
# Pack routes read it, and its bundles carry this image's build as their
# receipt `source_build`. Render one project bundle from it here.
# The tracked module pass runs first; bundle rendering reuses those imports.
# Both checks run and either failure rejects the image.
RUN python -m yoke_core.tools.container_image_validation

# Every image consumer inherits this build-time release-identity gate. An
# explicit release version must match the installed wheel metadata exactly;
# snapshot/operator builds that omit it still may not ship setuptools-scm's
# unresolved fallback while advertising a source build SHA.
RUN YOKE_EXPECTED_ENGINE_VERSION="$YOKE_ENGINE_VERSION" python -c \
    "import os, importlib.util; from importlib.metadata import version; assert importlib.util.find_spec('runtime') is None, 'server image contains development runtime package'; from yoke_contracts.engine_version import UNRESOLVED_SCM_FALLBACK_VERSION as fallback; actual=version('yoke-core'); expected=os.environ.get('YOKE_EXPECTED_ENGINE_VERSION', ''); build=os.environ.get('YOKE_BUILD_SHA', ''); assert actual and (not expected or actual == expected), f'installed yoke-core version {actual!r} does not match expected {expected!r}'; assert not build or actual != fallback, f'build {build!r} installed unresolved yoke-core fallback {actual!r}'"

# Fail the image build unless the installed product resolver can execute both
# portability clients with all runtime shared-library dependencies present.
RUN YOKE_MACHINE_HOME=/var/lib/yoke/.yoke python -c "from yoke_core.domain import universe_portability as p; import subprocess; [subprocess.run([p._postgres_executable(name), '--version'], check=True) for name in ('pg_restore', 'pg_dump')]"

USER yoke

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "yoke_core.api.container_healthcheck"]

CMD ["python", "-m", "yoke_core.api.server_entrypoint"]

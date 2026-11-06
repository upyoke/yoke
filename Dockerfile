# No `# syntax=` frontend pin: this file uses only builtin-frontend features,
# and an external frontend directive makes every build fetch that image from
# Docker Hub first — one more registry round-trip that can fail the whole
# build on a transient network error before any real work starts.

# Public GHCR copy of the official image, refreshed by ci-image-mirror.
# One ARG so both stages pull the same image without upstream registry quotas.
ARG PYTHON_IMAGE=ghcr.io/upyoke/python:3.13-slim

FROM ${PYTHON_IMAGE} AS tools
RUN python -m pip install uv==0.12.1

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
    uv sync --locked --no-default-groups --no-editable --no-install-workspace --compile-bytecode

WORKDIR /app

# The checksum-verified PostgreSQL operation is an ancestor of the final image,
# so mode=min retains it without publishing source or wheel-building layers.
RUN --mount=type=bind,source=packages/yoke-contracts/src,target=/bootstrap/contracts \
    --mount=type=bind,source=packages/yoke-cli/src,target=/bootstrap/cli \
    --mount=type=bind,source=packages/yoke-core/src/yoke_core/domain/postgres_binaries.py,target=/bootstrap/postgres_binaries.py \
    PYTHONPATH=/bootstrap/contracts:/bootstrap/cli YOKE_MACHINE_HOME=/tmp/postgres-bootstrap \
    python -c "import runpy, shutil; binaries = runpy.run_path('/bootstrap/postgres_binaries.py')['ensure_binaries'](); shutil.move(str(binaries.parent), '/opt/yoke-postgres'); shutil.rmtree('/tmp/postgres-bootstrap')"

FROM runtime-base AS builder

WORKDIR /build

# Source and setuptools scratch live only in this writable bind mount. The
# cache receives wheels, never another copy of the application source tree.
ARG YOKE_ENGINE_VERSION=""

RUN --mount=type=bind,source=.,target=/build,rw \
    --mount=type=bind,from=tools,source=/usr/local/bin/uv,target=/usr/local/bin/uv \
    if [ -n "$YOKE_ENGINE_VERSION" ]; then \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CONTRACTS="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CLI="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_HARNESS="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CORE="$YOKE_ENGINE_VERSION"; \
    fi; \
    uv build --wheel --all-packages --out-dir /wheels \
    && python packages/yoke-core/src/yoke_core/tools/wheel_module_completeness.py \
        --package-root packages/yoke-core/src/yoke_core \
        --wheel /wheels/yoke_core-*.whl

FROM runtime-base AS runtime

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
# Independent processes retain both checks and both exit codes. Parallel
# validation runs both import passes concurrently on the critical path.
RUN python -m yoke_core.tools.product_wheel_validation & wheel_pid=$!; \
    python -m yoke_core.tools.container_bundle_validation verify; bundle_status=$?; \
    wait "$wheel_pid"; wheel_status=$?; \
    test "$wheel_status" -eq 0 && test "$bundle_status" -eq 0

# Every image consumer inherits this build-time release-identity gate. An
# explicit release version must match the installed wheel metadata exactly;
# snapshot/operator builds that omit it still may not ship setuptools-scm's
# unresolved fallback while advertising a source build SHA.
RUN YOKE_EXPECTED_ENGINE_VERSION="$YOKE_ENGINE_VERSION" python -c \
    "import os; from importlib.metadata import version; from yoke_contracts.engine_version import UNRESOLVED_SCM_FALLBACK_VERSION as fallback; actual=version('yoke-core'); expected=os.environ.get('YOKE_EXPECTED_ENGINE_VERSION', ''); build=os.environ.get('YOKE_BUILD_SHA', ''); assert actual and (not expected or actual == expected), f'installed yoke-core version {actual!r} does not match expected {expected!r}'; assert not build or actual != fallback, f'build {build!r} installed unresolved yoke-core fallback {actual!r}'"

# Fail the image build unless the installed product resolver can execute both
# portability clients with all runtime shared-library dependencies present.
RUN YOKE_MACHINE_HOME=/var/lib/yoke/.yoke python -c "from yoke_core.domain import universe_portability as p; import subprocess; [subprocess.run([p._postgres_executable(name), '--version'], check=True) for name in ('pg_restore', 'pg_dump')]"

USER yoke

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "yoke_core.api.container_healthcheck"]

CMD ["python", "-m", "yoke_core.api.server_entrypoint"]

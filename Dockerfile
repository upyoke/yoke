# syntax=docker/dockerfile:1.7

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN python -m pip install --upgrade pip build wheel

COPY pyproject.toml ./
COPY .git_archival.txt ./
COPY runtime ./runtime
COPY packages ./packages

# Portability runs pg_restore/pg_dump inside the server. Fetch the same
# checksum-verified PostgreSQL build that local mode pins in product code.
RUN PYTHONPATH=/build/packages/yoke-contracts/src \
        YOKE_MACHINE_HOME=/var/lib/yoke \
        python -c "import runpy; runpy.run_path('/build/packages/yoke-core/src/yoke_core/domain/postgres_binaries.py')['ensure_binaries']()"

ARG YOKE_ENGINE_VERSION=""

# Build the root `yoke` wheel (the runtime* tree) plus the four split packages
# under packages/yoke-*/src. The split package names may also exist on public
# indexes, so the wheelhouse first receives dependency-free local wheels, then
# pins those exact versions while resolving external dependencies. That keeps a
# public same-name package from replacing the in-repo wheel.
RUN if [ -n "$YOKE_ENGINE_VERSION" ]; then \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CONTRACTS="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CLI="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_HARNESS="$YOKE_ENGINE_VERSION"; \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_YOKE_CORE="$YOKE_ENGINE_VERSION"; \
    fi; \
    python -m pip wheel --no-deps --wheel-dir /wheels ./packages/yoke-contracts \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./packages/yoke-cli \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./packages/yoke-harness \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./packages/yoke-core \
    && python packages/yoke-core/src/yoke_core/tools/local_wheel_constraints.py \
        /wheels yoke-contracts yoke-cli yoke-harness yoke-core \
        > /tmp/yoke-local-constraints.txt \
    && python -m pip wheel --wheel-dir /wheels --find-links /wheels \
        --constraint /tmp/yoke-local-constraints.txt .

FROM python:3.13-slim AS runtime

# The git short sha this image was built from; /v1/health serves it as
# `build` so deploy gates can assert WHICH code is answering.
ARG YOKE_BUILD_SHA=""
ARG YOKE_ENGINE_VERSION=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOKE_API_HOST=0.0.0.0 \
    YOKE_API_PORT=8765 \
    YOKE_MACHINE_HOME=/var/lib/yoke \
    YOKE_SERVER_TREE_ROOT=/srv/yoke-tree \
    YOKE_BUILD_SHA=${YOKE_BUILD_SHA}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system yoke \
    && adduser --system --ingroup yoke --home /var/lib/yoke yoke \
    && mkdir -p /var/lib/yoke \
    && chown -R yoke:yoke /var/lib/yoke

COPY --chown=yoke:yoke --from=builder /var/lib/yoke/postgres /var/lib/yoke/postgres

# Bundle sources live OUTSIDE the runtime package, so the wheel install
# cannot serve them; install-bundle and template routes read them from
# the declared server tree (YOKE_SERVER_TREE_ROOT) with repo layout.
COPY packs /srv/yoke-tree/packs
COPY .agents /srv/yoke-tree/.agents
COPY runtime/harness/claude/agents /srv/yoke-tree/runtime/harness/claude/agents
COPY runtime/harness/claude/rules /srv/yoke-tree/runtime/harness/claude/rules
COPY runtime/harness/codex/agents /srv/yoke-tree/runtime/harness/codex/agents
COPY AGENTS.md /srv/yoke-tree/AGENTS.md
COPY CODEX.md /srv/yoke-tree/CODEX.md
COPY .yoke/docs /srv/yoke-tree/.yoke/docs

COPY --from=builder /wheels /wheels

RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels \
        yoke yoke-contracts yoke-cli yoke-harness yoke-core \
    && rm -rf /wheels

# Every image consumer inherits this build-time release-identity gate. An
# explicit release version must match the installed wheel metadata exactly;
# snapshot/operator builds that omit it still may not ship setuptools-scm's
# unresolved fallback while advertising a source build SHA.
RUN YOKE_EXPECTED_ENGINE_VERSION="$YOKE_ENGINE_VERSION" python -c \
    "import os; from importlib.metadata import version; from yoke_contracts.engine_version import UNRESOLVED_SCM_FALLBACK_VERSION as fallback; actual=version('yoke-core'); expected=os.environ.get('YOKE_EXPECTED_ENGINE_VERSION', ''); build=os.environ.get('YOKE_BUILD_SHA', ''); assert actual and (not expected or actual == expected), f'installed yoke-core version {actual!r} does not match expected {expected!r}'; assert not build or actual != fallback, f'build {build!r} installed unresolved yoke-core fallback {actual!r}'"

# Fail the image build unless the installed product resolver can execute both
# portability clients with all runtime shared-library dependencies present.
RUN python -c "from yoke_core.domain import universe_portability as p; import subprocess; [subprocess.run([p._postgres_executable(name), '--version'], check=True) for name in ('pg_restore', 'pg_dump')]"

USER yoke

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "yoke_core.api.container_healthcheck"]

CMD ["python", "-m", "yoke_core.api.server_entrypoint"]

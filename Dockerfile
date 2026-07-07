# syntax=docker/dockerfile:1.7

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN python -m pip install --upgrade pip build wheel

COPY pyproject.toml ./
COPY runtime ./runtime
COPY packages ./packages

# Build the root `yoke` wheel (the runtime* tree) plus the four split packages
# under packages/yoke-*/src. yoke_core imports runtime.* (64 modules) and
# yoke_harness, so the runtime image needs all five distributions — the old
# `pip wheel .` shipped only runtime* and the container crashed on startup with
# `ModuleNotFoundError: No module named 'yoke_core'`. Build in dependency order
# with an accumulating --find-links so inter-package deps (yoke-cli ->
# yoke-contracts, yoke-core -> yoke-cli/yoke-contracts) resolve from
# /wheels instead of PyPI (where these private packages do not exist).
RUN python -m pip wheel --wheel-dir /wheels ./packages/yoke-contracts \
    && python -m pip wheel --wheel-dir /wheels --find-links /wheels ./packages/yoke-cli \
    && python -m pip wheel --wheel-dir /wheels --find-links /wheels ./packages/yoke-harness \
    && python -m pip wheel --wheel-dir /wheels --find-links /wheels ./packages/yoke-core \
    && python -m pip wheel --wheel-dir /wheels --find-links /wheels .

FROM python:3.13-slim AS runtime

# The git short sha this image was built from; /v1/health serves it as
# `build` so deploy gates can assert WHICH code is answering.
ARG YOKE_BUILD_SHA=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOKE_API_HOST=0.0.0.0 \
    YOKE_API_PORT=8765 \
    YOKE_MACHINE_HOME=/var/lib/yoke \
    YOKE_SERVER_TREE_ROOT=/srv/yoke-tree \
    YOKE_BUILD_SHA=${YOKE_BUILD_SHA}

WORKDIR /app

RUN addgroup --system yoke \
    && adduser --system --ingroup yoke --home /var/lib/yoke yoke \
    && mkdir -p /var/lib/yoke \
    && chown -R yoke:yoke /var/lib/yoke

# Bundle sources live OUTSIDE the runtime package, so the wheel install
# cannot serve them; install-bundle and template routes read them from
# the declared server tree (YOKE_SERVER_TREE_ROOT) with repo layout.
COPY templates /srv/yoke-tree/templates
COPY .agents /srv/yoke-tree/.agents
COPY runtime/harness/claude/agents /srv/yoke-tree/runtime/harness/claude/agents
COPY runtime/harness/claude/rules /srv/yoke-tree/runtime/harness/claude/rules
COPY runtime/harness/codex/agents /srv/yoke-tree/runtime/harness/codex/agents

COPY --from=builder /wheels /wheels

RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels \
        yoke yoke-contracts yoke-cli yoke-harness yoke-core \
    && rm -rf /wheels

USER yoke

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "yoke_core.api.container_healthcheck"]

CMD ["python", "-m", "yoke_core.api.server_entrypoint"]

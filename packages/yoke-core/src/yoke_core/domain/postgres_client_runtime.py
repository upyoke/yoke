"""Resolve standalone Postgres clients against Yoke's pinned engine."""

from __future__ import annotations

from yoke_core.domain import postgres_binaries, postgres_cluster


def postgres_executable(name: str) -> str:
    """Resolve the pinned Postgres client, falling back to ``PATH``.

    The pinned directory carries the same engine version as local mode:
    ``YOKE_PG_BIN_DIR`` when a source command isolated its machine home,
    otherwise the installed one. Standalone Postgres operations share this
    resolver so an older system client cannot silently replace it. Only an
    environment with no pinned engine uses ``PATH``. Server images pin an
    image-owned directory independently of the selected machine home.
    """
    return postgres_cluster.executable(postgres_binaries.pinned_bin_dir(), name)


__all__ = ["postgres_executable"]

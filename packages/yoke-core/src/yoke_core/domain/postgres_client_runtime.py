"""Resolve standalone Postgres clients against Yoke's pinned engine."""

from __future__ import annotations

from yoke_core.domain import postgres_binaries, postgres_cluster


def postgres_executable(name: str) -> str:
    """Resolve a bundled Postgres client, falling back to ``PATH``.

    The bundled directory carries the same pinned engine version as local
    mode. Standalone Postgres operations share this resolver so an older
    system client cannot silently replace an installed bundled client.
    """
    return postgres_cluster.executable(
        postgres_binaries.installed_bin_dir(),
        name,
    )


__all__ = ["postgres_executable"]

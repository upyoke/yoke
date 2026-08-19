"""Package-layout facts for the agent context packet.

Sibling of :mod:`schema_api_context`. The ``architecture_model``
family's ``package_roots`` section is the authority for where an
importable package's source lives; this module reads it and reconciles
it with the curated seed the packet renders, exactly as
``schema_api_context._resolve_columns`` reconciles live table columns
with their seed.

Why the packet cannot render straight from the model: rendered agent
adapters are committed files whose bytes a byte-identity test
re-derives, and a checkout with no project rows (CI, a fresh clone) has
no model to read. Rendering from the seed keeps the bytes stable
everywhere; reading the model turns any divergence into reported drift
instead of silent staleness.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional, Tuple

PackageRoots = Mapping[str, Tuple[Tuple[str, str], ...]]

# Human gloss for each layout the model declares. Keyed by the model's
# own vocabulary so a new layout surfaces as a missing key rather than a
# silently wrong sentence.
LAYOUT_GLOSS: dict[str, str] = {
    "package_under_root": "the package directory sits under the root",
    "package_is_root": "the root directory IS the package, so the "
    "package name never appears on disk",
}


def live_package_roots(project_id: str | int) -> Optional[PackageRoots]:
    """Return the project's declared ``package_roots``, or None.

    None means "no model to compare against" — an unreachable control
    plane, a checkout with no project rows, or a model that declares no
    package layout. Every failure is advisory: the caller renders from
    the seed and reports nothing.
    """
    try:
        from yoke_contracts.control_plane_locality import local_authority_exempt
        from yoke_core.domain import db_backend
        from yoke_core.domain.architecture_context_data import (
            load_architecture_model,
            package_roots_from_model,
        )
    except ImportError:
        return None
    try:
        import psycopg

        # Declared exempt for the same reason the sibling schema probe
        # is: reading IS the question, and any failure means "no model",
        # never a fallback to some other authority.
        with local_authority_exempt():
            conn = psycopg.connect(db_backend.resolve_pg_dsn(), autocommit=True)
    except Exception:
        return None
    try:
        model = load_architecture_model(conn, project_id)
    except Exception:
        return None
    finally:
        conn.close()
    roots = package_roots_from_model(model)
    return roots or None


def describe_drift(
    *, seed_roots: PackageRoots, live_roots: PackageRoots,
) -> list[str]:
    """Return one description per package whose declared roots differ."""
    drift: list[str] = []
    for package in sorted(set(seed_roots) | set(live_roots)):
        seeded = tuple(seed_roots.get(package, ()))
        declared = tuple(live_roots.get(package, ()))
        if seeded == declared:
            continue
        if not declared:
            drift.append(
                f"seed declares package roots for {package} but "
                f"architecture_model.package_roots has no such package"
            )
        elif not seeded:
            drift.append(
                f"architecture_model.package_roots declares {package} but "
                f"the packet seed has no such package"
            )
        else:
            drift.append(
                f"seed declares {package} roots {_format(seeded)} but "
                f"architecture_model.package_roots declares {_format(declared)}"
            )
    return drift


def packet_project_id() -> str:
    """Project whose declared layout the packet describes."""
    return os.environ.get("YOKE_PACKET_PROJECT", "yoke")


def resolve_package_roots() -> tuple[PackageRoots, list[str]]:
    """Return the roots the packet renders plus any divergence from the model.

    The seed is what renders — see this module's docstring for why — and
    the returned drift list is empty whenever no model is reachable to
    compare against.
    """
    from yoke_core.domain.schema_api_context_seed import PACKAGE_ROOTS

    seed_roots: PackageRoots = dict(PACKAGE_ROOTS)
    live = live_package_roots(packet_project_id())
    if live is None:
        return seed_roots, []
    return seed_roots, describe_drift(seed_roots=seed_roots, live_roots=live)


def _format(roots: Tuple[Tuple[str, str], ...]) -> str:
    return ", ".join(f"{root} ({layout})" for root, layout in roots)


__all__ = [
    "LAYOUT_GLOSS",
    "PackageRoots",
    "describe_drift",
    "live_package_roots",
    "packet_project_id",
    "resolve_package_roots",
]

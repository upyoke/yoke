"""Compatibility validation for typed capability documents in archives."""

from __future__ import annotations

from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)


def validate_restored_capabilities(conn: object) -> None:
    """Refuse capability documents the deployed engine cannot consume."""
    from yoke_core.domain.universe_portability import ArchiveCompatibilityError

    rows = conn.execute(  # type: ignore[attr-defined]
        "SELECT p.slug, pc.type, COALESCE(pc.settings, '{}')"
        " FROM project_capabilities pc"
        " JOIN projects p ON p.id = pc.project_id"
        " ORDER BY p.slug, pc.type"
    ).fetchall()
    for project_slug, capability_type, settings in rows:
        try:
            canonicalize_capability_settings(
                str(capability_type),
                str(settings),
            )
        except ValueError as exc:
            raise ArchiveCompatibilityError(
                f"project {str(project_slug)!r} capability"
                f" {str(capability_type)!r} is incompatible with the"
                f" deployed engine: {exc}"
            ) from exc


__all__ = ["validate_restored_capabilities"]

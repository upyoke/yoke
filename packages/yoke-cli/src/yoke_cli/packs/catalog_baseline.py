"""Installed-baseline and listing rules that depend on the selected Pack catalog."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from yoke_cli.packs.catalog_source import PackCatalog, catalog_spec
from yoke_cli.packs.errors import PackClientError
from yoke_contracts.packs import PACK_CATALOG_SERVED


def baseline_bundle(
    project: str,
    slug: str,
    record: Mapping[str, Any],
    catalog: PackCatalog,
    *,
    fetch: Callable[..., dict[str, Any]],
    session_id: str | None,
) -> dict[str, Any]:
    """Re-render an installed version as the three-way merge baseline.

    The baseline is read from the selected catalog and must reproduce the
    recorded content exactly. A version installed before release from a lane
    or merged commit therefore resolves against the served catalog only once
    a release carries that same version; until then the update names the
    recorded source to read it from instead.
    """

    version = record["version"]
    recorded = dict(record["source"])
    try:
        bundle = fetch(
            project,
            slug,
            version=version,
            render_values=record["render_values"],
            session_id=session_id,
            catalog=catalog,
        )
    except PackClientError as exc:
        if recorded == catalog.source():
            raise
        raise PackClientError(
            _unavailable(slug, version, recorded, catalog, str(exc))
        ) from exc
    if bundle["content_digest"] != record["content_digest"]:
        raise PackClientError(
            _unavailable(
                slug,
                version,
                recorded,
                catalog,
                "its rendered content differs from the recorded baseline",
            )
        )
    return bundle


def overlay_catalog_rows(
    served_rows: list[dict[str, Any]],
    descriptors: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Restate served Pack status rows against a pre-release catalog's versions."""

    by_slug = {str(row["slug"]): dict(row) for row in served_rows}
    rows: list[dict[str, Any]] = []
    for slug in sorted(set(by_slug) | set(descriptors)):
        row = by_slug.get(slug, {"slug": slug, "installed_version": None})
        descriptor = descriptors.get(slug)
        if descriptor is not None:
            latest = str(descriptor.get("latest_version") or "")
            record = (descriptor.get("versions") or {}).get(latest) or {}
            row.update(
                {
                    "name": descriptor.get("name", row.get("name", slug)),
                    "description": descriptor.get(
                        "description", row.get("description", "")
                    ),
                    "latest_version": latest,
                    "dependencies": list(record.get("dependencies") or []),
                    "prerequisites": list(record.get("prerequisites") or []),
                    "documentation": record.get("documentation"),
                    "file_count": len(record.get("files") or []),
                }
            )
        installed = row.get("installed_version")
        reasons = [
            reason
            for reason in row.get("stale_reasons") or []
            if reason != "update_available"
        ]
        if installed and installed != row.get("latest_version"):
            reasons.insert(0, "update_available")
        row["stale_reasons"] = reasons
        row["status"] = (
            "available" if not installed else "stale" if reasons else "installed"
        )
        row["in_catalog"] = descriptor is not None
        rows.append(row)
    return rows


def _unavailable(
    slug: str,
    version: str,
    recorded: Mapping[str, str],
    catalog: PackCatalog,
    detail: str,
) -> str:
    origin = (
        "the served catalog"
        if recorded.get("kind") == PACK_CATALOG_SERVED
        else f"{recorded['kind']} commit {recorded['commit']}"
    )
    code = (
        "pack-source-unreleased"
        if catalog.served and recorded.get("kind") != PACK_CATALOG_SERVED
        else "pack-baseline-unavailable"
    )
    return (
        f"{code}: Pack {slug!r} {version} was installed from {origin}, and the "
        f"{catalog.label()} cannot reproduce that baseline ({detail}); rerun with "
        f"--catalog {catalog_spec(recorded)}, or wait for a release that carries "
        f"{slug} {version}"
    )


__all__ = ["baseline_bundle", "overlay_catalog_rows"]

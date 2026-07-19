"""Versioned Pack discovery and project-specific bundle rendering."""

import base64
import hashlib
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.packs import (
    PACK_BUNDLE_SCHEMA,
    PACKS_SOURCE,
)
from yoke_core.domain import json_helper
from yoke_core.domain.install_bundle import server_tree_root
from yoke_core.domain.pack_catalog_validation import (
    PLACEHOLDER_PATTERN as _PLACEHOLDER,
    SLUG_PATTERN as _SLUG,
    PackError,
    PackNotFoundError,
    required_render_keys as _required_render_keys,
    validate_catalog_graph as _validate_catalog_graph,
    validate_descriptor as _validate_descriptor,
    validate_render_values as _validate_render_values,
    validate_target as _validate_target,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.pack_render import render_pack_text
from yoke_core.domain.project_renderer_pulumi import gather_pulumi_values
from yoke_core.domain.project_renderer_settings import _load_project_renderer_settings

def packs_root() -> Path:
    root = server_tree_root() / PACKS_SOURCE
    if not root.is_dir():
        raise PackError(f"Pack source directory is missing: {root}")
    return root


def list_pack_descriptors() -> list[dict[str, Any]]:
    """Return every validated Pack descriptor in stable slug order."""

    descriptors = [
        load_pack_descriptor(path.name)
        for path in sorted(packs_root().iterdir())
        if path.is_dir() and (path / "pack.json").is_file()
    ]
    _validate_catalog_graph(descriptors)
    return descriptors


def load_pack_descriptor(slug: str) -> dict[str, Any]:
    """Load and validate one Pack's root descriptor."""

    safe = str(slug).strip()
    if not _SLUG.fullmatch(safe):
        raise PackNotFoundError(f"Pack slug is invalid: {slug!r}")
    path = packs_root() / safe / "pack.json"
    if not path.is_file():
        raise PackNotFoundError(f"Pack {safe!r} is not available")
    try:
        raw = json_helper.load_path(path)
    except (OSError, ValueError) as exc:
        raise PackError(f"Pack descriptor is unreadable: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PackError(f"Pack descriptor root must be an object: {path}")
    descriptor = dict(raw)
    _validate_descriptor(descriptor, path)
    return descriptor


def catalog_rows() -> list[dict[str, Any]]:
    """Return the stable UI/API catalog projection from Pack source."""

    rows: list[dict[str, Any]] = []
    for descriptor in list_pack_descriptors():
        version = descriptor["latest_version"]
        version_record = descriptor["versions"][version]
        rows.append(
            {
                "slug": descriptor["slug"],
                "name": descriptor["name"],
                "description": descriptor["description"],
                "latest_version": version,
                "dependencies": list(version_record.get("dependencies") or []),
                "documentation": version_record["documentation"],
                "settings_schema": dict(version_record["settings_schema"]),
                "verification": list(version_record["verification"]),
                "file_count": _version_file_count(descriptor, version),
            }
        )
    return rows


def pack_version_root(slug: str, version: str | None = None) -> Path:
    """Return the validated source root for one immutable Pack version."""

    descriptor = load_pack_descriptor(slug)
    return _version_root(descriptor, version or descriptor["latest_version"])


def build_pack_bundle(
    conn: Any,
    *,
    project: str,
    pack: str,
    version: str | None = None,
    render_values: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Render one immutable Pack version for one registered project."""

    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise LookupError(f"project {project!r} not found")
    descriptor = load_pack_descriptor(pack)
    selected = version or descriptor["latest_version"]
    version_record = _version_record(descriptor, selected)
    required_keys = _required_render_keys(descriptor, selected)
    if render_values is None:
        settings = _load_project_renderer_settings(conn, identity.slug)
        available_values = gather_pulumi_values(
            identity.slug, server_tree_root(), settings
        )
        missing = sorted(required_keys - set(available_values))
        if missing:
            raise PackError(
                f"Pack {descriptor['slug']!r} requires unavailable render values: "
                + ", ".join(missing)
            )
        selected_values = {key: available_values[key] for key in sorted(required_keys)}
    else:
        selected_values = _validate_render_values(
            descriptor["slug"], required_keys, render_values
        )
    entries = _render_version_files(descriptor, selected, selected_values)
    return {
        "bundle_schema": PACK_BUNDLE_SCHEMA,
        "project_id": identity.id,
        "project_slug": identity.slug,
        "pack": descriptor["slug"],
        "name": descriptor["name"],
        "description": descriptor["description"],
        "version": selected,
        "latest_version": descriptor["latest_version"],
        "dependencies": list(version_record.get("dependencies") or []),
        "documentation": version_record["documentation"],
        "settings_schema": dict(version_record["settings_schema"]),
        "verification": list(version_record["verification"]),
        "render_values": selected_values,
        "files": entries,
        "content_digest": _content_digest(entries),
    }



def _version_record(descriptor: Mapping[str, Any], version: str) -> dict[str, Any]:
    versions = descriptor["versions"]
    if version not in versions:
        known = ", ".join(sorted(versions))
        raise PackNotFoundError(
            f"Pack {descriptor['slug']!r} has no version {version!r}; known: {known}"
        )
    return dict(versions[version])


def _version_root(descriptor: Mapping[str, Any], version: str) -> Path:
    record = _version_record(descriptor, version)
    return packs_root() / descriptor["slug"] / record["source"]


def _version_file_count(descriptor: Mapping[str, Any], version: str) -> int:
    return len(_version_record(descriptor, version)["files"])


def _render_version_files(
    descriptor: Mapping[str, Any],
    version: str,
    values: Mapping[str, str],
) -> list[dict[str, Any]]:
    record = _version_record(descriptor, version)
    root = _version_root(descriptor, version)
    entries: list[dict[str, Any]] = []
    targets: set[str] = set()
    for file_record in record["files"]:
        path = root / file_record["source"]
        raw_content = path.read_bytes()
        try:
            content = raw_content.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content = base64.b64encode(raw_content).decode("ascii")
            encoding = "base64"
        source_rel = file_record["source"]
        should_render = file_record["render"] == "install"
        target = (
            render_pack_text(file_record["target"], values)
            if should_render
            else file_record["target"]
        )
        _validate_target(target, path)
        rendered = (
            (
                render_pack_text(content, values).rstrip("\n") + "\n"
                if should_render
                else content
            )
            if encoding == "utf-8"
            else content
        )
        if should_render and (_PLACEHOLDER.search(target) or (
            encoding == "utf-8" and _PLACEHOLDER.search(rendered)
        )):
            raise PackError(f"Pack {descriptor['slug']!r} retains placeholders in {source_rel}")
        if target in targets:
            raise PackError(f"Pack {descriptor['slug']!r} renders duplicate target {target!r}")
        targets.add(target)
        mode = int(file_record["mode"], 8)
        rendered_bytes = (
            rendered.encode("utf-8")
            if encoding == "utf-8"
            else base64.b64decode(rendered.encode("ascii"))
        )
        entries.append(
            {
                "path": target,
                "content": rendered,
                "encoding": encoding,
                "sha256": hashlib.sha256(rendered_bytes).hexdigest(),
                "mode": mode,
            }
        )
    return entries



def _content_digest(entries: list[dict[str, Any]]) -> str:
    material = [
        {
            "path": row["path"],
            "sha256": row["sha256"],
            "mode": row["mode"],
            "encoding": row["encoding"],
        }
        for row in entries
    ]
    return hashlib.sha256(json_helper.dumps_compact(material).encode("utf-8")).hexdigest()


__all__ = [
    "PackError",
    "PackNotFoundError",
    "build_pack_bundle",
    "catalog_rows",
    "list_pack_descriptors",
    "load_pack_descriptor",
    "pack_version_root",
    "packs_root",
]

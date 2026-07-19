"""Versioned Pack discovery and project-specific bundle rendering."""

import base64
import hashlib
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from yoke_contracts.packs import (
    PACK_BUNDLE_SCHEMA,
    PACK_DESCRIPTOR_SCHEMA,
    PACKS_SOURCE,
)
from yoke_core.domain import json_helper
from yoke_core.domain.install_bundle import is_bundle_junk_path, server_tree_root
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.pack_render import render_pack_text
from yoke_core.domain.project_renderer_pulumi import gather_pulumi_values
from yoke_core.domain.project_renderer_settings import _load_project_renderer_settings


_SLUG = re.compile(r"^[a-z][a-z0-9-]*$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_PLACEHOLDER = re.compile(r"(?<!\$)\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


class PackError(RuntimeError):
    """Pack catalog or rendering is invalid; the message names the repair."""


class PackNotFoundError(PackError):
    """The requested Pack or version is not present in the catalog."""


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


def _validate_descriptor(descriptor: Mapping[str, Any], path: Path) -> None:
    if descriptor.get("schema") != PACK_DESCRIPTOR_SCHEMA:
        raise PackError(f"Unsupported Pack descriptor schema in {path}")
    slug = descriptor.get("slug")
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise PackError(f"Invalid Pack slug in {path}")
    if slug != path.parent.name:
        raise PackError(f"Pack slug {slug!r} does not match directory {path.parent.name!r}")
    for key in ("name", "description", "latest_version"):
        if not isinstance(descriptor.get(key), str) or not descriptor[key].strip():
            raise PackError(f"Pack {slug!r} requires non-empty {key}")
    versions = descriptor.get("versions")
    if not isinstance(versions, dict) or not versions:
        raise PackError(f"Pack {slug!r} requires a versions object")
    if descriptor["latest_version"] not in versions:
        raise PackError(f"Pack {slug!r} latest_version is not present in versions")
    for version, record in versions.items():
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise PackError(f"Pack {slug!r} has invalid version {version!r}")
        if not isinstance(record, dict):
            raise PackError(f"Pack {slug!r} version {version!r} must be an object")
        source = record.get("source")
        if not isinstance(source, str) or not source:
            raise PackError(f"Pack {slug!r} version {version!r} requires source")
        source_path = Path(source)
        if source_path.is_absolute() or ".." in source_path.parts:
            raise PackError(f"Pack {slug!r} version {version!r} has unsafe source")
        root = path.parent / source_path
        if not root.is_dir():
            raise PackError(f"Pack {slug!r} version {version!r} source is missing: {root}")
        dependencies = record.get("dependencies") or []
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) or not _SLUG.fullmatch(item)
            for item in dependencies
        ):
            raise PackError(f"Pack {slug!r} version {version!r} has invalid dependencies")
        documentation = record.get("documentation")
        if not isinstance(documentation, str) or not documentation:
            raise PackError(
                f"Pack {slug!r} version {version!r} requires documentation"
            )
        documentation_path = Path(documentation)
        if documentation_path.is_absolute() or ".." in documentation_path.parts:
            raise PackError(
                f"Pack {slug!r} version {version!r} has unsafe documentation"
            )
        if not (root / documentation_path).is_file():
            raise PackError(
                f"Pack {slug!r} version {version!r} documentation is missing: "
                f"{root / documentation_path}"
            )
        _validate_version_contract(slug, version, record, root)


def _validate_version_contract(
    slug: str,
    version: str,
    record: Mapping[str, Any],
    root: Path,
) -> None:
    schema = record.get("settings_schema")
    if not isinstance(schema, dict) or set(schema) != {
        "type", "properties", "required", "additionalProperties"
    }:
        raise PackError(
            f"Pack {slug!r} version {version!r} settings_schema is invalid"
        )
    properties = schema.get("properties")
    required = schema.get("required")
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        or len(required) != len(set(required))
        or set(required) != set(properties)
    ):
        raise PackError(
            f"Pack {slug!r} version {version!r} settings_schema must declare "
            "one required string property per install-time setting"
        )
    for key, field in properties.items():
        if (
            not isinstance(key, str)
            or not _PLACEHOLDER.fullmatch("{{" + key + "}}")
            or not isinstance(field, dict)
            or field.get("type") != "string"
            or not isinstance(field.get("description"), str)
            or not field["description"].strip()
        ):
            raise PackError(
                f"Pack {slug!r} version {version!r} has invalid setting {key!r}"
            )

    files = record.get("files")
    if not isinstance(files, list) or not files:
        raise PackError(f"Pack {slug!r} version {version!r} requires files")
    source_names: set[str] = set()
    target_names: set[str] = set()
    discovered_settings: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {
            "source", "target", "mode", "render"
        }:
            raise PackError(
                f"Pack {slug!r} version {version!r} has an invalid file record"
            )
        source = entry.get("source")
        target = entry.get("target")
        mode = entry.get("mode")
        render = entry.get("render")
        if not isinstance(source, str) or not source:
            raise PackError(f"Pack {slug!r} version {version!r} file source is invalid")
        source_path = Path(source)
        if source_path.is_absolute() or ".." in source_path.parts:
            raise PackError(f"Pack {slug!r} version {version!r} file source is unsafe")
        if not isinstance(target, str):
            raise PackError(f"Pack {slug!r} version {version!r} file target is invalid")
        _validate_target(target, root / source_path)
        if source in source_names or target in target_names:
            raise PackError(
                f"Pack {slug!r} version {version!r} repeats source or target {source!r}"
            )
        source_names.add(source)
        target_names.add(target)
        path = root / source_path
        if not path.is_file() or is_bundle_junk_path(path):
            raise PackError(
                f"Pack {slug!r} version {version!r} source is missing: {path}"
            )
        if mode not in {"0644", "0755"} or render not in {"install", "copy"}:
            raise PackError(
                f"Pack {slug!r} version {version!r} file policy is invalid: {source}"
            )
        raw = path.read_bytes()
        expected_mode = (
            "0755"
            if stat.S_IMODE(path.stat().st_mode) & 0o111 or raw.startswith(b"#!")
            else "0644"
        )
        if mode != expected_mode:
            raise PackError(
                f"Pack {slug!r} version {version!r} mode does not match source: {source}"
            )
        if render == "install":
            discovered_settings.update(_PLACEHOLDER.findall(target))
            try:
                discovered_settings.update(_PLACEHOLDER.findall(raw.decode("utf-8")))
            except UnicodeDecodeError:
                pass
    actual_sources = {
        candidate.relative_to(root).as_posix()
        for candidate in root.rglob("*")
        if candidate.is_file() and not is_bundle_junk_path(candidate)
    }
    if source_names != actual_sources:
        missing = sorted(actual_sources - source_names)
        unknown = sorted(source_names - actual_sources)
        raise PackError(
            f"Pack {slug!r} version {version!r} file inventory mismatch; "
            f"missing={missing}, unknown={unknown}"
        )
    if discovered_settings != set(required):
        raise PackError(
            f"Pack {slug!r} version {version!r} settings do not match its "
            f"install-time placeholders: {sorted(discovered_settings)}"
        )
    documentation = str(record["documentation"])
    if documentation not in target_names:
        raise PackError(
            f"Pack {slug!r} version {version!r} documentation is not installed"
        )

    verification = record.get("verification")
    if not isinstance(verification, list) or not verification:
        raise PackError(
            f"Pack {slug!r} version {version!r} requires verification entrypoints"
        )
    names: set[str] = set()
    for entry in verification:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"name", "command"}
            or not isinstance(entry.get("name"), str)
            or not entry["name"].strip()
            or entry["name"] in names
            or not isinstance(entry.get("command"), str)
            or not entry["command"].strip()
        ):
            raise PackError(
                f"Pack {slug!r} version {version!r} verification is invalid"
            )
        names.add(entry["name"])


def _validate_catalog_graph(descriptors: list[Mapping[str, Any]]) -> None:
    slugs = {str(row["slug"]) for row in descriptors}
    graph: dict[str, list[str]] = {}
    declared_target_owners: dict[str, str] = {}
    for descriptor in descriptors:
        slug = str(descriptor["slug"])
        record = descriptor["versions"][descriptor["latest_version"]]
        dependencies = list(record.get("dependencies") or [])
        unknown = sorted(set(dependencies) - slugs)
        if unknown:
            raise PackError(f"Pack {slug!r} has unknown dependencies: {unknown}")
        graph[slug] = dependencies
        for version, version_record in descriptor["versions"].items():
            for file_record in version_record["files"]:
                target = str(file_record["target"])
                owner = declared_target_owners.get(target)
                if owner is not None and owner != slug:
                    raise PackError(
                        f"Pack {slug!r} version {version!r} overlaps target "
                        f"{target!r} owned by Pack {owner!r}"
                    )
                declared_target_owners[target] = slug
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(slug: str) -> None:
        if slug in visiting:
            raise PackError(f"Pack dependency cycle includes {slug!r}")
        if slug in visited:
            return
        visiting.add(slug)
        for dependency in graph[slug]:
            visit(dependency)
        visiting.remove(slug)
        visited.add(slug)

    for slug in sorted(graph):
        visit(slug)


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


def _required_render_keys(
    descriptor: Mapping[str, Any], version: str
) -> set[str]:
    record = _version_record(descriptor, version)
    return set(record["settings_schema"]["required"])


def _validate_render_values(
    slug: str,
    required_keys: set[str],
    render_values: Mapping[str, str],
) -> dict[str, str]:
    values = dict(render_values)
    invalid = sorted(key for key, value in values.items() if not isinstance(value, str))
    if invalid:
        raise PackError(
            f"Pack {slug!r} render values must be strings: " + ", ".join(invalid)
        )
    missing = sorted(required_keys - set(values))
    unknown = sorted(set(values) - required_keys)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise PackError(f"Pack {slug!r} render values are invalid: " + "; ".join(details))
    return {key: values[key] for key in sorted(values)}


def _validate_target(target: str, source: Path) -> None:
    target_path = Path(target)
    if (
        not target
        or target_path.is_absolute()
        or ".." in target_path.parts
        or target_path.parts[0] == ".yoke"
    ):
        raise PackError(f"Pack source {source} renders unsafe target {target!r}")


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

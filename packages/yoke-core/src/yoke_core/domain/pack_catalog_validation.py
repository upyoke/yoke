"""Descriptor, dependency-graph, settings, and target validation for Packs."""

from pathlib import Path
import re
import stat
from typing import Any, Mapping

from yoke_contracts.packs import PACK_DESCRIPTOR_SCHEMA
from yoke_core.domain.install_bundle import is_bundle_junk_path


SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PLACEHOLDER_PATTERN = re.compile(r"(?<!\$)\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


class PackError(RuntimeError):
    """Pack catalog or rendering is invalid; the message names the repair."""


class PackNotFoundError(PackError):
    """The requested Pack or version is not present in the catalog."""


def validate_descriptor(descriptor: Mapping[str, Any], path: Path) -> None:
    if descriptor.get("schema") != PACK_DESCRIPTOR_SCHEMA:
        raise PackError(f"Unsupported Pack descriptor schema in {path}")
    slug = descriptor.get("slug")
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
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
        if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
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
            not isinstance(item, str) or not SLUG_PATTERN.fullmatch(item)
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
            or not PLACEHOLDER_PATTERN.fullmatch("{{" + key + "}}")
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
        validate_target(target, root / source_path)
        if source in source_names or target in target_names:
            raise PackError(
                f"Pack {slug!r} version {version!r} repeats source or target {source!r}"
            )
        source_names.add(source)
        target_names.add(target)
        source_file = root / source_path
        if not source_file.is_file() or is_bundle_junk_path(source_file):
            raise PackError(
                f"Pack {slug!r} version {version!r} source is missing: {source_file}"
            )
        if mode not in {"0644", "0755"} or render not in {"install", "copy"}:
            raise PackError(
                f"Pack {slug!r} version {version!r} file policy is invalid: {source}"
            )
        raw = source_file.read_bytes()
        expected_mode = (
            "0755"
            if stat.S_IMODE(source_file.stat().st_mode) & 0o111 or raw.startswith(b"#!")
            else "0644"
        )
        if mode != expected_mode:
            raise PackError(
                f"Pack {slug!r} version {version!r} mode does not match source: {source}"
            )
        if render == "install":
            discovered_settings.update(PLACEHOLDER_PATTERN.findall(target))
            try:
                discovered_settings.update(PLACEHOLDER_PATTERN.findall(raw.decode("utf-8")))
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
    _validate_verification(slug, version, record)


def _validate_verification(
    slug: str, version: str, record: Mapping[str, Any]
) -> None:
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


def validate_catalog_graph(descriptors: list[Mapping[str, Any]]) -> None:
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


def required_render_keys(
    descriptor: Mapping[str, Any], version: str
) -> set[str]:
    return set(descriptor["versions"][version]["settings_schema"]["required"])


def validate_render_values(
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


def validate_target(target: str, source: Path) -> None:
    target_path = Path(target)
    if (
        not target
        or target_path.is_absolute()
        or ".." in target_path.parts
        or target_path.parts[0] == ".yoke"
    ):
        raise PackError(f"Pack source {source} renders unsafe target {target!r}")


__all__ = [
    "PLACEHOLDER_PATTERN",
    "SLUG_PATTERN",
    "PackError",
    "PackNotFoundError",
    "required_render_keys",
    "validate_catalog_graph",
    "validate_descriptor",
    "validate_render_values",
    "validate_target",
]

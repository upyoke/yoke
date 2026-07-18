"""Validation for project artifact bundles, manifests, and checkout paths."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    normalize_github_repository,
    validate_github_web_endpoint,
)
from yoke_contracts.project_artifacts import (
    PROJECT_ARTIFACT_BUNDLE_SCHEMA,
    PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX,
    PROJECT_ARTIFACT_MANIFEST_REL,
    PROJECT_ARTIFACT_MANIFEST_SCHEMA,
    PROJECT_ARTIFACT_PACKAGED_SOURCE,
    PROJECT_ARTIFACT_SOURCE_DEV_SOURCE,
    PROJECT_ARTIFACT_TEMPLATE,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_PREFIXES = (
    ".github/workflows/",
    PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX,
    "infra/",
    "ops/",
)
_MANIFEST_KEYS = frozenset(
    {
        "manifest_schema",
        "project_id",
        "project_slug",
        "template",
        "template_version",
        "yoke_version",
        "template_source",
        "template_digest",
        "settings_digest",
        "content_digest",
        "checkout_identity",
        "artifact_policy",
        "artifacts",
    }
)


class ProjectArtifactError(RuntimeError):
    """Artifact reconciliation cannot proceed safely."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(content: str) -> str:
    return sha256_bytes(content.encode("utf-8"))


def resolve_repo_root(value: str | Path | None) -> Path:
    root = Path(value or os.getcwd()).expanduser().resolve()
    if not root.is_dir():
        raise ProjectArtifactError(f"repo root is not a directory: {root}")
    return root


def validate_bundle(bundle: Any, *, source_dev_admin: bool) -> list[dict[str, Any]]:
    if not isinstance(bundle, Mapping):
        raise ProjectArtifactError("artifact bundle must be a JSON object")
    if bundle.get("bundle_schema") != PROJECT_ARTIFACT_BUNDLE_SCHEMA:
        raise ProjectArtifactError(
            f"artifact bundle schema {bundle.get('bundle_schema')!r} is not "
            f"supported ({PROJECT_ARTIFACT_BUNDLE_SCHEMA})"
        )
    if bundle.get("template") != PROJECT_ARTIFACT_TEMPLATE:
        raise ProjectArtifactError("artifact bundle names an unsupported template")
    source = str(bundle.get("template_source") or "")
    _validate_template_source(source, source_dev_admin=source_dev_admin)
    project_id, project_slug = _validate_bundle_metadata(bundle)
    _validate_checkout_identity(
        bundle.get("checkout_identity"),
        project_id,
        project_slug,
    )
    _validate_artifact_policy(bundle.get("artifact_policy"))
    return _validate_bundle_entries(bundle)


def _validate_template_source(source: str, *, source_dev_admin: bool) -> None:
    allowed_sources = {PROJECT_ARTIFACT_PACKAGED_SOURCE}
    if source_dev_admin:
        allowed_sources.add(PROJECT_ARTIFACT_SOURCE_DEV_SOURCE)
    if source not in allowed_sources:
        if source_dev_admin:
            raise ProjectArtifactError(
                f"artifact bundle returned an unknown template source: {source!r}"
            )
        raise ProjectArtifactError(
            "product artifact refresh requires the packaged template mirror; "
            f"server returned {source!r}"
        )


def _validate_bundle_metadata(bundle: Mapping[str, Any]) -> tuple[int, str]:
    for key in (
        "template_version",
        "yoke_version",
        "template_digest",
        "settings_digest",
        "content_digest",
        "project_slug",
    ):
        value = bundle.get(key)
        if not isinstance(value, str) or not value:
            raise ProjectArtifactError(f"artifact bundle {key} is missing")
    for key in ("template_digest", "settings_digest", "content_digest"):
        if not _SHA256_RE.fullmatch(str(bundle[key])):
            raise ProjectArtifactError(f"artifact bundle {key} is not sha256")
    project_id = bundle.get("project_id")
    if (
        isinstance(project_id, bool)
        or not isinstance(project_id, int)
        or project_id <= 0
    ):
        raise ProjectArtifactError("artifact bundle project_id must be positive")
    return project_id, str(bundle["project_slug"])


def _validate_bundle_entries(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_entries = bundle.get("artifacts")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ProjectArtifactError("artifact bundle contains no artifacts")
    entries: list[dict[str, Any]] = []
    paths: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise ProjectArtifactError("artifact bundle entry must be an object")
        path = str(raw.get("path") or "")
        content = raw.get("content")
        digest = raw.get("sha256")
        mode = raw.get("mode")
        validate_managed_path(path, source="artifact bundle")
        if path in paths:
            raise ProjectArtifactError(f"artifact bundle duplicates {path!r}")
        paths.add(path)
        if not isinstance(content, str):
            raise ProjectArtifactError(f"artifact {path!r} content is not text")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ProjectArtifactError(f"artifact {path!r} digest is not sha256")
        if sha256_text(content) != digest:
            raise ProjectArtifactError(
                f"artifact {path!r} digest does not match content"
            )
        if mode not in (0o644, 0o755):
            raise ProjectArtifactError(f"artifact {path!r} mode is unsupported")
        entries.append(
            {
                "path": path,
                "content": content,
                "sha256": digest,
                "mode": mode,
            }
        )
    material = [
        {"path": e["path"], "sha256": e["sha256"], "mode": e["mode"]} for e in entries
    ]
    if json_digest(material) != bundle["content_digest"]:
        raise ProjectArtifactError(
            "artifact bundle content_digest does not match entries"
        )
    return sorted(entries, key=lambda entry: entry["path"])


def _validate_checkout_identity(
    value: Any,
    project_id: int,
    project_slug: str,
) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "project_id",
        "project_slug",
        "github_repo",
        "github_web_url",
    }:
        raise ProjectArtifactError("artifact bundle checkout_identity is invalid")
    if value.get("project_id") != project_id:
        raise ProjectArtifactError(
            "artifact bundle checkout_identity project id does not match"
        )
    identity_slug = value.get("project_slug")
    if not isinstance(identity_slug, str) or identity_slug != project_slug:
        raise ProjectArtifactError(
            "artifact bundle checkout_identity project slug does not match"
        )
    repo = value.get("github_repo")
    web_url = value.get("github_web_url")
    if repo is None and web_url is None:
        return
    if not isinstance(repo, str) or not isinstance(web_url, str):
        raise ProjectArtifactError("artifact bundle checkout_identity is invalid")
    try:
        canonical_web = validate_github_web_endpoint(web_url).base_url
        canonical_repo = normalize_github_repository(
            repo,
            web_url=canonical_web,
        )
    except GitHubApiOriginError as exc:
        raise ProjectArtifactError(
            f"artifact bundle checkout_identity is invalid: {exc}"
        ) from exc
    if canonical_web != web_url or canonical_repo != repo:
        raise ProjectArtifactError(
            "artifact bundle checkout_identity must use canonical values"
        )


def _validate_artifact_policy(value: Any) -> None:
    expected = {
        "generated_reference_prefix": (PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX),
        "project_owned_prefixes": [".yoke/runbooks/"],
        "deviation_policy": "preserve-and-refuse",
        "prune_policy": "manifest-owned-only",
    }
    if value != expected:
        raise ProjectArtifactError(
            "artifact bundle policy does not match this CLI's safety contract"
        )


def validate_managed_path(raw: str, *, source: str) -> None:
    path = Path(raw)
    if (
        not raw
        or path.is_absolute()
        or ".." in path.parts
        or not any(raw.startswith(prefix) for prefix in _ALLOWED_PREFIXES)
        or raw == PROJECT_ARTIFACT_MANIFEST_REL
    ):
        raise ProjectArtifactError(
            f"{source} names unsafe managed artifact path {raw!r}"
        )


def load_manifest(repo_root: Path) -> dict[str, Any] | None:
    assert_paths_safe(repo_root, [PROJECT_ARTIFACT_MANIFEST_REL], context="manifest")
    path = repo_root / PROJECT_ARTIFACT_MANIFEST_REL
    if path.is_symlink():
        raise ProjectArtifactError("artifact manifest must not be a symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise ProjectArtifactError("artifact manifest is not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectArtifactError(f"artifact manifest is unreadable: {exc}") from exc
    validate_manifest(payload)
    return payload


def validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise ProjectArtifactError("artifact manifest must contain an object")
    unknown = sorted(set(manifest) - _MANIFEST_KEYS)
    if unknown:
        raise ProjectArtifactError(
            "artifact manifest contains unknown mutation-bearing keys: "
            + ", ".join(unknown)
        )
    if manifest.get("manifest_schema") != PROJECT_ARTIFACT_MANIFEST_SCHEMA:
        raise ProjectArtifactError(
            f"artifact manifest schema {manifest.get('manifest_schema')!r} "
            f"is not supported ({PROJECT_ARTIFACT_MANIFEST_SCHEMA})"
        )
    if manifest.get("template") != PROJECT_ARTIFACT_TEMPLATE:
        raise ProjectArtifactError("artifact manifest template is unsupported")
    project_id = manifest.get("project_id")
    if (
        isinstance(project_id, bool)
        or not isinstance(project_id, int)
        or project_id <= 0
    ):
        raise ProjectArtifactError("artifact manifest project_id must be positive")
    for key in (
        "project_slug",
        "template_version",
        "yoke_version",
        "template_source",
        "template_digest",
        "settings_digest",
        "content_digest",
    ):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ProjectArtifactError(f"artifact manifest {key} is missing")
    _validate_template_source(
        str(manifest["template_source"]),
        source_dev_admin=True,
    )
    _validate_checkout_identity(
        manifest.get("checkout_identity"),
        project_id,
        str(manifest.get("project_slug") or ""),
    )
    _validate_artifact_policy(manifest.get("artifact_policy"))
    for key in ("template_digest", "settings_digest", "content_digest"):
        if not _SHA256_RE.fullmatch(manifest[key]):
            raise ProjectArtifactError(f"artifact manifest {key} is not sha256")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ProjectArtifactError("artifact manifest artifacts must be an object")
    for path, record in artifacts.items():
        if not isinstance(path, str):
            raise ProjectArtifactError("artifact manifest contains a non-string path")
        validate_managed_path(path, source="artifact manifest")
        if not isinstance(record, dict) or set(record) != {"sha256", "mode"}:
            raise ProjectArtifactError(f"artifact manifest record {path!r} is invalid")
        if not isinstance(record["sha256"], str) or not _SHA256_RE.fullmatch(
            record["sha256"]
        ):
            raise ProjectArtifactError(f"artifact manifest digest {path!r} is invalid")
        if record["mode"] not in (0o644, 0o755):
            raise ProjectArtifactError(f"artifact manifest mode {path!r} is invalid")


def assert_paths_safe(repo_root: Path, paths: Iterable[str], *, context: str) -> None:
    root = repo_root.resolve()
    for raw in paths:
        if raw != PROJECT_ARTIFACT_MANIFEST_REL:
            validate_managed_path(raw, source=context)
        candidate = root / raw
        current = root
        for part in Path(raw).parts:
            current = current / part
            if current.is_symlink():
                raise ProjectArtifactError(
                    f"{context} path {raw!r} crosses symlink component {current}"
                )
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ProjectArtifactError(
                f"{context} path {raw!r} cannot be resolved safely: {exc}"
            ) from exc
        if resolved != root and root not in resolved.parents:
            raise ProjectArtifactError(
                f"{context} path {raw!r} resolves outside repo root"
            )


def assert_targets_plannable(repo_root: Path, paths: Iterable[str]) -> None:
    selected = list(paths)
    assert_paths_safe(repo_root, selected, context="artifact preflight")
    root = repo_root.resolve()
    for raw in selected:
        target = root / raw
        if target.exists() and not target.is_file():
            raise ProjectArtifactError(
                f"artifact target {raw!r} exists but is not a regular file"
            )
        parent = target.parent
        while parent != root and not parent.exists():
            parent = parent.parent
        if not parent.is_dir():
            raise ProjectArtifactError(
                f"artifact target {raw!r} has a non-directory parent"
            )


def json_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


__all__ = [
    "ProjectArtifactError",
    "assert_paths_safe",
    "assert_targets_plannable",
    "json_digest",
    "load_manifest",
    "resolve_repo_root",
    "sha256_bytes",
    "sha256_text",
    "validate_bundle",
    "validate_managed_path",
    "validate_manifest",
]

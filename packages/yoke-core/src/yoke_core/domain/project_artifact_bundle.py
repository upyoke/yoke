"""Render the managed-project artifact bundle from packaged templates.

The control plane owns template and settings authority.  This module renders
that authority into a deterministic, secret-free bundle; checkout inspection
and mutation remain client-local in :mod:`yoke_cli.project_artifacts`.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    github_web_url_from_api,
    normalize_github_repository,
)
from yoke_contracts.project_artifacts import (
    PROJECT_ARTIFACT_BUNDLE_SCHEMA,
    PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX,
    PROJECT_ARTIFACT_PACKAGED_SOURCE,
    PROJECT_ARTIFACT_SOURCE_DEV_SOURCE,
    PROJECT_ARTIFACT_TEMPLATE,
)
from yoke_core.domain.install_bundle import (
    _packaged_tree_root,
    is_bundle_junk_path,
    server_tree_root,
    yoke_version,
)
from yoke_core.domain.project_renderer import render_project
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    _table_exists,
    _load_project_renderer_settings,
)
from yoke_core.domain.project_renderer_settings_snapshot import (
    snapshot_from_settings,
)
from yoke_core.domain.project_identity import resolve_project


_SOURCE_DEV_ROOT_ENV = "YOKE_SERVER_TREE_ROOT"
_UNRESOLVED_PLACEHOLDER = re.compile(r"(?<!\$)\{\{[A-Za-z_][A-Za-z0-9_]*\}\}")
_RUNBOOK_DESTINATIONS = {
    "DEPLOY.md": f"{PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX}deploy.md",
    "DEPLOY-checklist.md": (
        f"{PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX}deploy-checklist.md"
    ),
    "RECOVERY.md": f"{PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX}recovery.md",
}
_STATIC_INFRA_NAMES = frozenset({"Pulumi.yaml", "requirements.txt"})
_STATIC_INFRA_SUFFIXES = frozenset({".py", ".mjs"})


class ProjectArtifactBundleError(RuntimeError):
    """The project artifact bundle cannot be rendered safely."""


def build_project_artifact_bundle(
    conn: Any,
    project: str,
    *,
    source_dev_admin: bool = False,
) -> dict[str, Any]:
    """Render a deterministic artifact bundle for any registered project.

    Product operation always reads the wheel-packaged template mirror.  The
    source-dev/admin override is deliberately double opt-in: the request flag
    and an explicit ``YOKE_SERVER_TREE_ROOT`` declaration are both required.
    """

    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise LookupError(f"project {project!r} not found")
    settings = _load_project_renderer_settings(conn, identity.slug)
    template_root, source = _template_root(source_dev_admin)
    artifacts = _render_artifacts(settings, template_root)
    _validate_rendered_artifacts(artifacts)

    settings_material = snapshot_from_settings(settings)
    settings_digest = _json_digest(settings_material)
    template_digest = _template_digest(template_root)
    content_digest = _entries_digest(artifacts)
    version = yoke_version()
    checkout_identity = _checkout_identity(
        conn,
        identity.id,
        identity.slug,
    )
    return {
        "bundle_schema": PROJECT_ARTIFACT_BUNDLE_SCHEMA,
        "project_id": identity.id,
        "project_slug": settings.project,
        "template": PROJECT_ARTIFACT_TEMPLATE,
        "template_version": f"{PROJECT_ARTIFACT_TEMPLATE}@{version}",
        "yoke_version": version,
        "template_source": source,
        "template_digest": template_digest,
        "settings_digest": settings_digest,
        "content_digest": content_digest,
        "checkout_identity": checkout_identity,
        "artifact_policy": {
            "generated_reference_prefix": (PROJECT_ARTIFACT_GENERATED_REFERENCE_PREFIX),
            "project_owned_prefixes": [".yoke/runbooks/"],
            "deviation_policy": "preserve-and-refuse",
            "prune_policy": "manifest-owned-only",
        },
        "artifacts": artifacts,
        "pulumi_stack_config": {
            "included": False,
            "reason": (
                "Pulumi stack YAML contains stack-scoped operator state; "
                "materialize it only with `yoke projects pulumi-stack-config "
                "get` or `yoke pulumi exec`."
            ),
        },
    }


def _checkout_identity(
    conn: Any,
    project_id: int,
    project_slug: str,
) -> dict[str, Any]:
    result = {
        "project_id": project_id,
        "project_slug": project_slug,
        "github_repo": None,
        "github_web_url": None,
    }
    if not _table_exists(conn, "project_github_repo_bindings"):
        return result
    row = conn.execute(
        "SELECT github_repo, api_url, status, last_verified_at "
        "FROM project_github_repo_bindings WHERE project_id=%s",
        (project_id,),
    ).fetchone()
    if row is None:
        return result
    github_repo = str(row["github_repo"] or "").strip()
    api_url = str(row["api_url"] or "").strip()
    status = str(row["status"] or "").strip()
    last_verified_at = str(row["last_verified_at"] or "").strip()
    if status != "active" or not last_verified_at:
        return result
    try:
        web_url = github_web_url_from_api(api_url)
        normalized = normalize_github_repository(
            github_repo,
            web_url=web_url,
        )
    except GitHubApiOriginError as exc:
        raise ProjectArtifactBundleError(
            f"project GitHub repository binding is invalid: {exc}"
        ) from exc
    result["github_repo"] = normalized
    result["github_web_url"] = web_url
    return result


def _template_root(source_dev_admin: bool) -> tuple[Path, str]:
    if not source_dev_admin:
        root = _packaged_tree_root()
        return root, PROJECT_ARTIFACT_PACKAGED_SOURCE
    declared = os.environ.get(_SOURCE_DEV_ROOT_ENV, "").strip()
    if not declared:
        raise ProjectArtifactBundleError(
            "source-dev/admin artifact rendering requires both the explicit "
            "request flag and YOKE_SERVER_TREE_ROOT naming the approved "
            "source checkout"
        )
    root = server_tree_root()
    if root.resolve() != Path(declared).expanduser().resolve():
        raise ProjectArtifactBundleError(
            "source-dev/admin template root does not match YOKE_SERVER_TREE_ROOT"
        )
    return root, PROJECT_ARTIFACT_SOURCE_DEV_SOURCE


def _render_artifacts(
    settings: ProjectRendererSettings,
    template_root: Path,
) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="yoke-artifact-render-") as raw:
        output = Path(raw)
        # The renderer's per-file progress belongs to a source-dev tool; the
        # function response is the structured server-safe receipt.
        with contextlib.redirect_stderr(io.StringIO()):
            for selected in (
                "DEPLOY.md",
                "DEPLOY-checklist.md",
                "RECOVERY.md",
                "workflows",
                "ops",
            ):
                render_project(
                    settings.project,
                    write=True,
                    only=selected,
                    project_root=template_root,
                    output_dir=output,
                    settings=settings,
                )
        entries: list[dict[str, Any]] = []
        for source_name, destination in _RUNBOOK_DESTINATIONS.items():
            path = output / source_name
            if path.is_file():
                entries.append(_entry(destination, path.read_text(), 0o644))
        workflow_dir = output / "workflows"
        if workflow_dir.is_dir():
            for path in sorted(workflow_dir.iterdir()):
                if path.is_file():
                    entries.append(
                        _entry(
                            f".github/workflows/{path.name}",
                            path.read_text(),
                            0o644,
                        )
                    )
        ops_dir = output / "ops"
        if ops_dir.is_dir():
            for path in sorted(ops_dir.iterdir()):
                if path.is_file():
                    entries.append(_entry(f"ops/{path.name}", path.read_text(), 0o755))
        entries.extend(_static_infra_entries(template_root))
    entries.sort(key=lambda entry: entry["path"])
    return entries


def _static_infra_entries(template_root: Path) -> list[dict[str, Any]]:
    source = template_root / "templates" / PROJECT_ARTIFACT_TEMPLATE / "infra"
    if not source.is_dir():
        raise ProjectArtifactBundleError(
            f"packaged static infrastructure template is missing: {source}"
        )
    entries: list[dict[str, Any]] = []
    for path in sorted(source.iterdir()):
        if not path.is_file() or is_bundle_junk_path(path):
            continue
        if path.name not in _STATIC_INFRA_NAMES and path.suffix not in (
            _STATIC_INFRA_SUFFIXES
        ):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectArtifactBundleError(
                f"static infrastructure template is not UTF-8 text: {path.name}"
            ) from exc
        entries.append(_entry(f"infra/{path.name}", content, 0o644))
    return entries


def _entry(path: str, content: str, mode: int) -> dict[str, Any]:
    normalized = content.rstrip("\n") + "\n"
    return {
        "path": path,
        "content": normalized,
        "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "mode": mode,
    }


def _validate_rendered_artifacts(entries: Iterable[Mapping[str, Any]]) -> None:
    paths: set[str] = set()
    unresolved: list[str] = []
    for entry in entries:
        path = str(entry.get("path") or "")
        if not path or path in paths:
            raise ProjectArtifactBundleError(
                f"rendered artifact path is empty or duplicated: {path!r}"
            )
        paths.add(path)
        content = str(entry.get("content") or "")
        if _UNRESOLVED_PLACEHOLDER.search(content):
            unresolved.append(path)
    if unresolved:
        raise ProjectArtifactBundleError(
            "rendered artifacts retain unresolved template placeholders: "
            + ", ".join(sorted(unresolved))
        )


def _template_digest(template_root: Path) -> str:
    source = template_root / "templates" / PROJECT_ARTIFACT_TEMPLATE
    records: list[dict[str, str]] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or is_bundle_junk_path(path):
            continue
        records.append(
            {
                "path": path.relative_to(source).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return _json_digest(records)


def _entries_digest(entries: Iterable[Mapping[str, Any]]) -> str:
    material = [
        {
            "path": str(entry["path"]),
            "sha256": str(entry["sha256"]),
            "mode": int(entry["mode"]),
        }
        for entry in entries
    ]
    return _json_digest(material)


def _json_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ProjectArtifactBundleError",
    "build_project_artifact_bundle",
]

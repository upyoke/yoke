"""Explicit source-dev/admin project refresh preview and apply.

The ordinary project refresh path continues to fetch the active product
environment's packaged bundle. This sibling path is selected only by an
explicit source checkout and never registers machine config, contacts a Yoke
environment, or writes snapshot state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import runner
from yoke_cli.project_install import source_dev
from yoke_cli.project_install.local_source_preview import (
    preserved_manifest_files,
    preview_report,
)
from yoke_cli.project_install.validate import _validate_bundle
from yoke_cli.project_install.files import ProjectInstallError


def refresh_from_source(
    repo_root: str | Path | None,
    *,
    source_checkout: str | Path,
    project_id: int | None,
    project_slug: str | None,
    manifest_from: str | Path | None,
    apply: bool,
) -> dict[str, Any]:
    """Preview or apply source-derived project files without server state."""
    root = files_layer.resolve_repo_root(repo_root)
    source = Path(source_checkout).expanduser().resolve()
    if not source_dev.is_yoke_source_checkout(source):
        raise ProjectInstallError(
            f"--source-checkout is not a Yoke source checkout: {source}"
        )
    if source_dev.is_yoke_source_checkout(root):
        raise ProjectInstallError(
            "source-dev/admin project refresh targets an external project "
            "checkout, not the Yoke source checkout"
        )
    prior_manifest, manifest_source = _resolve_prior_manifest(
        root, manifest_from
    )
    if apply and not prior_manifest:
        raise ProjectInstallError(
            "source-dev/admin refresh apply requires install-manifest lineage: "
            "use the target checkout's existing manifest or pass "
            "--manifest-from PATH for a linked worktree"
        )
    resolved_id = _resolve_project_id(project_id, prior_manifest)
    resolved_slug = _resolve_project_slug(project_slug, prior_manifest)
    bundle = _build_bundle(
        source,
        target_root=root,
        project_id=resolved_id,
        project_slug=resolved_slug,
        apply=apply,
    )
    _validate_bundle(bundle)
    if int(bundle.get("project_id", -1)) != resolved_id:
        raise ProjectInstallError(
            "source bundle project_id does not match the requested project"
        )
    preserved_files = preserved_manifest_files(
        root, bundle, prior_manifest
    )
    source_label = f"source-checkout:{source}"
    if not apply:
        return preview_report(
            root,
            bundle,
            prior_manifest=prior_manifest,
            manifest_source=manifest_source,
            source_label=source_label,
            preserved_files=preserved_files,
        )
    report = runner.apply_bundle(
        root,
        bundle,
        operation="refresh",
        source=source_label,
        prior_manifest=prior_manifest,
        preserved_manifest_files=preserved_files,
    )
    report.update({
        "preview": False,
        "source_dev_admin": True,
        "source_checkout": str(source),
        "manifest_source": manifest_source,
        "snapshot_sync": {
            "status": "skipped",
            "reason": (
                "source-dev/admin local-source refresh does not write "
                "external or server snapshot state"
            ),
        },
        "machine_config_newly_registered": False,
    })
    return report


def _resolve_prior_manifest(
    target_root: Path,
    manifest_from: str | Path | None,
) -> tuple[dict[str, Any], str]:
    target_manifest = files_layer.load_manifest(target_root)
    if manifest_from is None:
        return target_manifest or {}, (
            str(files_layer.manifest_path(target_root))
            if target_manifest is not None
            else "none"
        )
    source_path = Path(manifest_from).expanduser().resolve()
    transferred = files_layer.load_manifest_path(source_path)
    assert transferred is not None
    if target_manifest is not None and target_manifest != transferred:
        raise ProjectInstallError(
            "--manifest-from conflicts with the target checkout's existing "
            "install manifest; remove the flag or reconcile the manifests"
        )
    return transferred, str(source_path)


def _resolve_project_id(
    explicit: int | None, prior_manifest: dict[str, Any],
) -> int:
    inherited = prior_manifest.get("project_id")
    if explicit is None:
        if isinstance(inherited, int) and inherited > 0:
            return inherited
        raise ProjectInstallError(
            "source-dev/admin refresh requires --project-id N when no prior "
            "install manifest supplies project_id"
        )
    if explicit <= 0:
        raise ProjectInstallError("--project-id must be a positive integer")
    if isinstance(inherited, int) and inherited != explicit:
        raise ProjectInstallError(
            f"--project-id {explicit} conflicts with manifest project_id "
            f"{inherited}"
        )
    return explicit


def _resolve_project_slug(
    explicit: str | None, prior_manifest: dict[str, Any],
) -> str:
    inherited = str(prior_manifest.get("project_slug") or "").strip()
    selected = str(explicit or "").strip()
    if selected and inherited and selected != inherited:
        raise ProjectInstallError(
            f"--project-slug {selected!r} conflicts with manifest "
            f"project_slug {inherited!r}"
        )
    resolved = selected or inherited
    if not resolved:
        raise ProjectInstallError(
            "source-dev/admin refresh requires --project-slug SLUG when the "
            "prior install manifest does not record project_slug"
        )
    return resolved


def _build_bundle(
    source_checkout: Path,
    *,
    target_root: Path,
    project_id: int,
    project_slug: str,
    apply: bool,
) -> dict[str, Any]:
    source_roots = [
        source_checkout / "packages" / package / "src"
        for package in ("yoke-core", "yoke-contracts", "yoke-cli", "yoke-harness")
    ]
    command = [
        sys.executable,
        "-m",
        "yoke_core.tools.source_project_bundle",
        "--source-checkout",
        str(source_checkout),
        "--target-root",
        str(target_root),
        "--project-id",
        str(project_id),
        "--project-slug",
        project_slug,
    ]
    if apply:
        command.append("--apply")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [*(str(path) for path in source_roots), str(source_checkout)]
    )
    try:
        completed = subprocess.run(
            command,
            cwd=source_checkout,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectInstallError(
            f"source bundle process could not run: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if (
            "No module named yoke_core.tools.source_project_bundle" in detail
            or "source bundle imports are not bound" in detail
        ):
            detail = (
                "source bundle builder is absent from the explicit checkout; "
                "ambient Yoke source fallback was refused"
            )
        raise ProjectInstallError(
            "source bundle process failed for the explicit checkout: "
            + (detail or f"exit {completed.returncode}")
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProjectInstallError(
            f"source bundle process returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProjectInstallError("source bundle process did not return an object")
    return payload


__all__ = ["refresh_from_source"]

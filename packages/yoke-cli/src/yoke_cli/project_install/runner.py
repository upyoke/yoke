"""Product side of ``yoke project install`` / ``refresh`` / ``uninstall``.

One repo-bootstrap command for external project checkouts, with the product
copy delivery strategy:

* ``copy`` (external project repos, the default) — fetches the rendered
  operating layer from the CLI's active HTTPS env and writes it
  idempotently, tracked by ``.yoke/install-manifest.json`` so refresh
  can prune and uninstall can remove cleanly.
The Yoke source checkout is not a product install target. Its tracked
source-link/admin wiring is owned by the explicit ``yoke dev setup``
branch so normal project installs stay external-project safe.

Never written: credentials, the machine active env, the CLI binary, the
browser runtime, or any ``.yoke/`` path other than the manifest and the
seed-if-missing project contract. The bundle is authority for its own
``files``; contract files are seeded only when absent and become
project-owned the moment they land; project-authored content (including
foreign hook entries) is untouchable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from yoke_cli.config import machine_config
from yoke_cli.config import writer as machine_config_writer
from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.file_line_config_migration import (
    migrate_file_line_exceptions,
)
from yoke_cli.project_install.preflight import preflight_apply
from yoke_cli.project_install import source_dev
from yoke_cli.project_install.deployment_flows import (
    prepare_project_flow_declaration,
    preflight_project_flow_declaration,
    sync_project_flow_declarations_for_write,
)
from yoke_cli.project_install.files import (
    MODE_COPY,
    MODE_KEY,
    MODE_SOURCE_LINK,
    ProjectInstallError,
)
from yoke_cli.project_install.uninstall import uninstall
from yoke_cli.project_install.validate import validate_bundle_for_project
from yoke_cli.project_install.transport import (
    resolve_bundle as _resolve_bundle,
)

# Top-level manifest keys this CLI version authors; anything else found in
# an existing manifest is carried forward verbatim on rewrite.


def install(
    repo_root: str | Path | None = None,
    project_id: Optional[int] = None,
    explicit_env: Optional[str] = None,
    config_path: str | Path | None = None,
    *,
    operation: str = "install",
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Install (or refresh — same code path) the project-local layer.

    ``mode`` is retained for compatibility with direct callers; source-link
    setup now routes to ``yoke dev setup``.
    """
    root = files_layer.resolve_repo_root(repo_root)
    resolved_mode, reason = source_dev.resolve_mode(root, mode)
    print(
        f"yoke project {operation}: delivery strategy = {resolved_mode} "
        f"({reason})",
        file=sys.stderr,
    )
    git_hooks_layer.assert_pre_commit_runtime_available()
    resolved_id, explicit_given = _resolve_project_id(
        root, project_id, config_path
    )
    bundle, source = _resolve_bundle(
        resolved_id, explicit_env=explicit_env, config_path=config_path
    )
    validate_bundle_for_project(bundle, resolved_id)
    preflight_apply(root, bundle, files_layer.load_manifest(root) or {}, {})
    prepared_flows = prepare_project_flow_declaration(root)
    preflight_project_flow_declaration(
        project=str(bundle["project_slug"]),
        prepared=prepared_flows,
    )
    # Register between bundle resolution and apply: the fetch has already
    # validated the project id against the env (a 404 aborts before any
    # mapping is recorded), and an unwritable machine config fails fast
    # BEFORE the repo is touched. A mapping left by a later apply failure
    # is the same durable state `yoke project register` produces — a
    # plain rerun completes the install from it.
    registered = _register_in_machine_config(
        root, resolved_id, config_path, explicit_given
    )
    report = apply_bundle(root, bundle, operation=operation, source=source)
    # Runs after apply so the seeded .yoke/project.config exists to move into.
    report["file_line_config_migration"] = migrate_file_line_exceptions(root)
    report["deployment_flows"] = sync_project_flow_declarations_for_write(
        repo_root=root,
        project=str(bundle["project_slug"]),
        prepared=prepared_flows,
    )
    report["snapshot_sync"] = sync_local_snapshot_for_write(
        project=str(resolved_id),
        repo_root=str(root),
        integration_target=None,
        session_id=None,
    )
    report["machine_config_newly_registered"] = registered
    return report


def refresh(
    repo_root: str | Path | None = None,
    project_id: Optional[int] = None,
    explicit_env: Optional[str] = None,
    config_path: str | Path | None = None,
    *,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    return install(repo_root, project_id, explicit_env, config_path,
                   operation="refresh", mode=mode)




def _resolve_project_id(
    repo_root: Path,
    explicit: Optional[int],
    config_path: str | Path | None,
) -> Tuple[int, bool]:
    """Resolve project id: explicit flag > machine-config mapping > error."""
    if explicit is not None:
        return int(explicit), True
    mapped = machine_config.project_id(repo_root, config_path)
    if mapped is not None:
        return mapped, False
    raise ProjectInstallError(
        f"no project id for {repo_root}: pass --project-id N (the install "
        "will register the checkout mapping in machine config), or run "
        "`yoke project register` first"
    )


def _register_in_machine_config(
    repo_root: Path,
    project_id: int,
    config_path: str | Path | None,
    explicit_given: bool,
) -> bool:
    """Register the checkout->project mapping when install introduced it."""
    if not explicit_given:
        return False
    if machine_config.project_id(repo_root, config_path) is not None:
        return False
    machine_config_writer.register_project(
        repo_root, project_id, path=config_path
    )
    return True


__all__ = ["MODE_COPY", "MODE_KEY", "MODE_SOURCE_LINK",
           "ProjectInstallError", "apply_bundle", "install", "refresh",
           "uninstall"]

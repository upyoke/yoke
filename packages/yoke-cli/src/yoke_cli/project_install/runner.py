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
from yoke_cli.project_install.file_line_managed_exceptions import (
    ensure_managed_file_line_exceptions,
)
from yoke_cli.project_install.file_line_config_migration import (
    migrate_file_line_exceptions,
)
from yoke_cli.project_install.hooks_path_check import (
    collect_hooks_path_warnings,
)
from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install.preflight import preflight_apply
from yoke_cli.project_install import source_dev
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
    force: bool = False,
    commit: bool = True,
    require_default_branch: bool = True,
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
    raw_branch = bundle.get("default_branch")
    require_branch = (
        require_default_branch
        and isinstance(raw_branch, str)
        and bool(raw_branch.strip())
    )
    default_branch = (
        str(raw_branch).strip()
        if require_branch
        else checkout_gate.FALLBACK_DEFAULT_BRANCH
    )
    checkout = checkout_gate.assert_ready_for_write(
        root,
        default_branch=default_branch,
        force=force,
        require_default_branch=require_branch,
    )
    preflight_apply(root, bundle, files_layer.load_manifest(root) or {}, {})
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
    # A clean copy install can still be shadowed at commit time: a
    # core.hooksPath override sends git elsewhere, or a missing `yoke`
    # launcher leaves the shims unable to exec. Surface both loudly.
    if resolved_mode == MODE_COPY:
        report.setdefault("warnings", []).extend(
            collect_hooks_path_warnings(root)
        )
    # Runs after apply so the seeded .yoke/project.config exists to move into.
    report["file_line_config_migration"] = migrate_file_line_exceptions(root)
    # The install writes the managed rules files AND the gate that measures
    # them, so it also owns exempting them — otherwise a project's first
    # commit fails on the install's own output.
    report["file_line_managed_exceptions"] = ensure_managed_file_line_exceptions(
        root, _managed_markdown_paths(bundle),
    )
    report["snapshot_sync"] = sync_local_snapshot_for_write(
        project=str(resolved_id),
        repo_root=str(root),
        integration_target=None,
        session_id=None,
    )
    # Approval posture is machine-wide and the launcher install owns it;
    # folder trust is per path, so the checkout being installed is trusted
    # here. Without it a harness still stops to ask about the directory.
    try:
        from yoke_contracts.harness_folder_trust_grant import grant_folder_trust

        report["harness_folder_trust"] = grant_folder_trust(root)
    except Exception as exc:  # noqa: BLE001 — install must not fail on this
        report.setdefault("warnings", []).append(
            f"harness folder trust was not granted: {exc}"
        )
    report["machine_config_newly_registered"] = registered
    try:
        from yoke_cli.project_install.harness_machine_persist import (
            persist_install_glue,
        )

        persist_install_glue(root, int(resolved_id), report)
    except Exception as exc:
        report.setdefault("warnings", []).append(
            f"harness machine report was not persisted: {exc}"
        )
    report["checkout"] = checkout
    report["commit"] = checkout_gate.commit_touched_paths(
        root, report, skip=not commit, operation=operation,
    )
    return report


def refresh(
    repo_root: str | Path | None = None,
    project_id: Optional[int] = None,
    explicit_env: Optional[str] = None,
    config_path: str | Path | None = None,
    *,
    mode: Optional[str] = None,
    force: bool = False,
    commit: bool = True,
    require_default_branch: bool = True,
) -> Dict[str, Any]:
    return install(
        repo_root, project_id, explicit_env, config_path,
        operation="refresh", mode=mode, force=force, commit=commit,
        require_default_branch=require_default_branch,
    )




def _resolve_project_id(
    repo_root: Path,
    explicit: Optional[int],
    config_path: str | Path | None,
) -> Tuple[int, bool]:
    """Resolve project id against the active-env machine-config mapping.

    Authority is the checkout→project_id row for the selected env
    (``YOKE_ENV`` / ``--env`` / ``active_env``). An explicit ``--project-id``
    may introduce the first mapping for this checkout, but it cannot disagree
    with an existing active-env mapping, and it cannot invent a mapping when
    the checkout is already registered only under another env.
    """
    mapped = machine_config.project_id(repo_root, config_path)
    if mapped is not None:
        if explicit is not None and int(explicit) != mapped:
            raise ProjectInstallError(
                f"checkout {repo_root} is mapped to project_id {mapped} for "
                f"the active env; refusing requested project_id {int(explicit)}"
            )
        if explicit is not None:
            return mapped, True
        return mapped, False

    other_env = _other_env_checkout_mappings(repo_root, config_path)
    if other_env:
        details = ", ".join(
            f"project_id {entry['project_id']} on env "
            f"{entry.get('env') or '(untagged)'}"
            for entry in other_env
        )
        raise ProjectInstallError(
            f"checkout {repo_root} is mapped only for another env ({details}); "
            "refusing install/refresh on the active env. Register an explicit "
            "mapping for this env with `yoke project register`, or switch to "
            "the mapped env."
        )
    if explicit is not None:
        return int(explicit), True
    raise ProjectInstallError(
        f"no project id for {repo_root}: pass --project-id N (the install "
        "will register the checkout mapping in machine config), or run "
        "`yoke project register` first"
    )


def _other_env_checkout_mappings(
    repo_root: Path,
    config_path: str | Path | None,
) -> list[dict[str, Any]]:
    """Return this checkout's mappings that do not apply under the selected env."""
    from yoke_contracts.machine_config import schema as contract

    cfg = machine_config.load_config(config_path)
    try:
        env: str | None = contract.selected_env(cfg)
    except contract.MachineConfigContractError:
        env = None
    active = str(cfg.get("active_env") or "").strip()
    candidates = {
        _resolved_path_key(path)
        for path in contract.checkout_path_candidates(repo_root)
    }
    other: list[dict[str, Any]] = []
    for entry in contract.normalize_projects(cfg.get("projects")):
        if _resolved_path_key(Path(entry["checkout"]).expanduser()) not in candidates:
            continue
        if contract.entry_resolves_under_env(
            entry, env=env, active_env=active,
        ):
            continue
        other.append(entry)
    return other


def _resolved_path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _managed_markdown_paths(bundle: dict) -> list[str]:
    """Repo-relative paths of the rules files this bundle manages.

    Read from the bundle rather than hardcoded so the exemption set tracks
    whatever the server declares as managed-markdown targets. A bundle from
    an older server carries no targets and yields nothing to exempt.
    """
    managed = bundle.get("managed_markdown")
    if not isinstance(managed, dict):
        return []
    targets = managed.get("targets")
    if not isinstance(targets, list):
        return []
    paths: list[str] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        rel = target.get("path")
        if isinstance(rel, str) and rel:
            paths.append(rel)
    return paths


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

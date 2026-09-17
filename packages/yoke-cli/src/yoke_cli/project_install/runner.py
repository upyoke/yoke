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

from yoke_contracts.machine_config import checkout_env_mismatch

from yoke_cli.config import machine_config
from yoke_cli.config import writer as machine_config_writer
from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install import repository_layer
# Re-exported: ``project_install`` and the source-dev refresh path both reach
# the bundle write through this module's name.
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install import publication
from yoke_cli.project_install import publication_outcome
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
    publish: bool = True,
) -> Dict[str, Any]:
    """Install (or refresh — same code path) the project-local layer.

    ``mode`` is retained for compatibility with direct callers; source-link
    setup now routes to ``yoke dev setup``.

    The run generates against current upstream, commits the paths it owns,
    and then publishes that commit to the branch's remote. ``publish=False``
    keeps the commit local — the shape onboarding uses, because it configures
    the checkout's Git credentials only after the install has written.
    """
    root = files_layer.resolve_repo_root(repo_root)
    resolved_mode, reason = source_dev.resolve_mode(root, mode)
    print(
        f"yoke project {operation}: delivery strategy = {resolved_mode} ({reason})",
        file=sys.stderr,
    )
    git_hooks_layer.assert_pre_commit_runtime_available()
    resolved_id, explicit_given = _resolve_project_id(root, project_id, config_path)
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
    upstream = _bring_branch_current(root, checkout.get("branch") or default_branch)
    checkout["upstream"] = upstream
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

    def regenerate() -> Dict[str, Any]:
        return repository_layer.write_repository_layer(
            root, bundle, operation=operation, source=source, mode=resolved_mode,
        )

    report = regenerate()
    if upstream.get("warning"):
        report.setdefault("warnings", []).append(upstream["warning"])
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
        root,
        report,
        skip=not commit,
        operation=operation,
    )
    report["publication"] = publication.publish_installed_layer(
        root,
        report,
        commit=report["commit"],
        default_branch=str(checkout.get("branch") or ""),
        operation=operation,
        regenerate=regenerate,
        project_slug=str(bundle.get("project_slug") or "") or None,
        publish=publish,
    )
    publication_outcome.announce(report)
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
    publish: bool = True,
) -> Dict[str, Any]:
    return install(
        repo_root,
        project_id,
        explicit_env,
        config_path,
        operation="refresh",
        mode=mode,
        force=force,
        commit=commit,
        require_default_branch=require_default_branch,
        publish=publish,
    )


def _bring_branch_current(repo_root: Path, branch: str) -> Dict[str, Any]:
    """Generate against verified-current upstream, or record why it could not.

    The shared project freshness contract owns the fetch and the safe
    fast-forward. This call site owns one decision it deliberately does not
    delegate: preparation REFUSES when the remote cannot be read, because a
    lane then has no legitimate revision to start from, while install
    materializes a LOCAL layer and refusing would deny an offline machine the
    very thing it asked for. So the run degrades, records the reason as a
    warning, and lets publication carry the refusal — an unreachable remote
    ends as a pending publication naming the fetch failure, never as a claim
    that the remote holds the layer.

    ``local_branch_current`` is the signal kept here rather than
    ``lane_base_is_current``: this run commits onto the checked-out branch in
    place instead of cutting a lane, so what matters is whether THAT branch
    holds everything the remote does. A branch that is behind reports false
    here even though a lane cut from the fetched upstream would be current.
    """
    from yoke_cli.config import repo_upstream_freshness

    freshness = repo_upstream_freshness.refresh_base_branch(str(repo_root), branch)
    payload: Dict[str, Any] = {
        "state": freshness.state,
        "remote": freshness.remote,
        "branch": freshness.base_branch,
        "verified": freshness.verified,
        "local_branch_current": freshness.local_branch_current,
        "upstream_sha": freshness.upstream_sha,
        "ahead": freshness.ahead,
        "behind": freshness.behind,
    }
    if freshness.note:
        payload["note"] = freshness.note
        if freshness.needs_attention:
            payload["warning"] = freshness.note
    return payload


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

    other_env = checkout_env_mismatch.mismatch_note(
        repo_root, config_path=config_path,
    )
    if other_env:
        raise ProjectInstallError(
            f"refusing install/refresh on the selected env. {other_env}"
        )
    if explicit is not None:
        return int(explicit), True
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
    # explicit_given means the operator typed --project-id themselves: a
    # deliberate reconfiguration, not routine unattended execution.
    machine_config_writer.register_project(
        repo_root, project_id, reassign=True, path=config_path,
    )
    return True


__all__ = [
    "MODE_COPY",
    "MODE_KEY",
    "MODE_SOURCE_LINK",
    "ProjectInstallError",
    "apply_bundle",
    "install",
    "refresh",
    "uninstall",
]

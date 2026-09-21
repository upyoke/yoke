"""Pin a serving-API self-deploy driver to the run's ``release_lineage``.

A relayed project dispatches to a server running an installed build, which
cannot move underneath it. Only a self-deploy reads a live checkout, so only
that path takes a detached worktree at the pin. Relayed execution does not
take a checkout.

The freeze is the isolation: a merge landing on the live tree cannot mix
already-cached modules with files read later from disk. The per-stage
comparison makes any remaining drift a named halt. The halt does not
terminalize the run, so re-drive by correlation token still recovers it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from yoke_contracts.deployment_itemless_teaching import INTERRUPTED_RUN_RECOVERY
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain.project_checkout_locations import checkout_for_project_slug
from yoke_core.domain.worktree_paths import _run, captured_process_detail
from yoke_core.domain.worktree_provision import GIT_WORKTREE_ADD_TIMEOUT_SECONDS


PINNED_RELEASE_ENV = "YOKE_DEPLOY_DRIVER_RELEASE"
PINNED_SOURCE_ROOT_ENV = "YOKE_DEPLOY_DRIVER_SOURCE_ROOT"
DRIVER_SOURCE_DRIFT_PREFIX = "deploy driver source drift:"
# Distinct from step-runner failure so the pipeline can halt without
# calling fail_pipeline_stage (which would mark the run failed).
EXIT_DRIVER_SOURCE_DRIFT = -5
_YOKE_CORE_MARKER = Path("packages") / "yoke-core" / "src" / "yoke_core"


class DeployPinnedSourceError(RuntimeError):
    """Self-deploy driver source could not be frozen at the run pin."""


@dataclass(frozen=True)
class PinnedDriverSource:
    """Detached checkout the self-deploy child must execute from."""

    root: Path
    lineage: str


def _https_transport() -> bool:
    from yoke_core.domain.events_transport_guard import _active_transport_is_https

    return _active_transport_is_https()


def _yoke_shaped(root: Path) -> bool:
    return (root / _YOKE_CORE_MARKER).is_dir()


def _resolve_commit(repo: str, revision: str) -> str:
    result = _run(
        ["git", "-C", repo, "rev-parse", "--verify", f"{revision}^{{commit}}"]
    )
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _ensure_commit(repo: str, revision: str) -> str:
    resolved = _resolve_commit(repo, revision)
    if resolved:
        return resolved
    fetched = _run(
        ["git", "-C", repo, "fetch", "--quiet", "origin", revision],
        timeout=120,
    )
    resolved = _resolve_commit(repo, revision)
    if resolved:
        return resolved
    detail = captured_process_detail(fetched)
    raise DeployPinnedSourceError(
        f"pinned release_lineage {revision!r} is not a commit in {repo}: "
        f"{detail}. Fetch that revision into the machine-config checkout "
        "and re-drive the run."
    )


def driver_worktree_path(checkout: Path, run_id: str) -> Path:
    return checkout / ".worktrees" / f"deploy-{run_id}"


def ensure_pinned_worktree(checkout: str, run_id: str, revision: str) -> Path:
    """Reuse or add a detached worktree at *revision* for *run_id*."""
    sha = _ensure_commit(checkout, revision)
    path = driver_worktree_path(Path(checkout), run_id)
    if path.exists():
        existing = _resolve_commit(str(path), "HEAD")
        if existing == sha:
            return path
        raise DeployPinnedSourceError(
            f"self-deploy driver worktree {path} is at {existing or 'unknown'} "
            f"but run {run_id} pins {sha}; refuse rather than reset it. "
            "Remove that worktree only after confirming nothing is using it, "
            "then re-drive the run."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    added = _run(
        ["git", "-C", checkout, "worktree", "add", "--detach", str(path), sha],
        timeout=GIT_WORKTREE_ADD_TIMEOUT_SECONDS,
    )
    if added.returncode != 0:
        raise DeployPinnedSourceError(
            f"git worktree add --detach failed for {path} at {sha}: "
            f"{captured_process_detail(added)}"
        )
    return path


def prepare_self_deploy_driver(run_id: str) -> PinnedDriverSource | None:
    """Freeze driver source for a local self-deploy; None on the relayed path."""
    if _https_transport():
        return None
    context = control_plane.execution_context(run_id)
    run = context.get("run") or {}
    lineage = str(run.get("release_lineage") or "").strip()
    project = str(run.get("project") or "")
    if not lineage:
        raise DeployPinnedSourceError(
            f"deployment run {run_id} has no release_lineage to pin the "
            "self-deploy driver to"
        )
    checkout = checkout_for_project_slug(project)
    if checkout is None:
        raise DeployPinnedSourceError(
            f"no machine-config checkout for project {project!r}; a "
            "self-deploy driver cannot freeze source it cannot find"
        )
    checkout = checkout.expanduser().resolve()
    if not _yoke_shaped(checkout):
        return None
    root = ensure_pinned_worktree(str(checkout), run_id, lineage)
    return PinnedDriverSource(root=root, lineage=_ensure_commit(str(checkout), lineage))


def driver_source_drift_refusal(release_lineage: str) -> str | None:
    """Named halt when the executing tree is not the run pin.

    No-op when the pin env is unset so relayed drivers and pipeline tests
    that call ``run_pipeline`` directly stay unchanged.
    """
    pinned = os.environ.get(PINNED_RELEASE_ENV, "").strip()
    root = os.environ.get(PINNED_SOURCE_ROOT_ENV, "").strip()
    if not pinned and not root:
        return None
    recovery = INTERRUPTED_RUN_RECOVERY.strip()
    if not pinned or not root:
        return (
            f"{DRIVER_SOURCE_DRIFT_PREFIX} incomplete pin "
            f"({PINNED_RELEASE_ENV}={pinned!r}, "
            f"{PINNED_SOURCE_ROOT_ENV}={root!r}). {recovery}"
        )
    pinned_root = Path(root).resolve()
    executing = _resolve_commit(root, "HEAD")
    expected = _resolve_commit(root, release_lineage) or _resolve_commit(
        root, pinned
    )
    loaded = Path(__file__).resolve()
    pin_module = (
        pinned_root
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "domain"
        / "deploy_pipeline_pinned_source.py"
    )
    loaded_ok = True
    if pin_module.is_file():
        try:
            loaded.relative_to(pinned_root)
        except ValueError:
            loaded_ok = False
    pin_resolved = _resolve_commit(root, pinned)
    if executing and expected and executing == expected and loaded_ok:
        if not pin_resolved or pin_resolved == expected:
            return None
    return (
        f"{DRIVER_SOURCE_DRIFT_PREFIX} driver is executing "
        f"{executing or 'unknown'} loaded from {loaded}, pin env "
        f"{pinned}, run release_lineage {release_lineage}. Halt without "
        f"changing run status so the same run stays re-drivable.\n{recovery}"
    )


__all__ = [
    "DRIVER_SOURCE_DRIFT_PREFIX",
    "DeployPinnedSourceError",
    "EXIT_DRIVER_SOURCE_DRIFT",
    "PINNED_RELEASE_ENV",
    "PINNED_SOURCE_ROOT_ENV",
    "PinnedDriverSource",
    "driver_source_drift_refusal",
    "driver_worktree_path",
    "ensure_pinned_worktree",
    "prepare_self_deploy_driver",
]

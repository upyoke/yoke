"""Automatic module retirement after successful live-apply.

When a governed migration completes (every declared module reaches
``migration_audit.state='completed'`` on the authoritative DB) and the
model declares **single-install topology** (per
:mod:`yoke_core.domain.migration_install_topology`), the module file
and its sibling ``test_<module>.py`` can retire in the same slice as
live-apply — there is no fan-out to wait for. This module owns the
deletion step and stages it through ``git rm`` so the advance skill's
finalize commit picks it up.

Behavior is deliberately quiet on the multi-install path: the helper
returns an empty result and emits no events. Multi-install
authoritative deletion still routes through the post-merge cutover
slice as before.

Safety contract:

* Only runs after every module in ``profile.migration_modules`` has a
  ``migration_audit.state='completed'`` row referencing the model's
  authoritative DB. Partial completion is never enough.
* Only runs from within a checkout that contains the module file
  (``worktree_path/<modules_dir>/<identifier>.py``). When the file is
  already absent the helper records the no-op and continues.
* Only runs ``git rm`` (not raw ``rm``); the deletion stages for the
  next commit without bypassing git's working-tree consistency model.
* Emits ``MigrationModuleRetired`` (or ``MigrationModuleRetireSkipped``
  with a structured ``reason``) so reviewers can audit what fired and
  what didn't.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from yoke_core.domain.events import emit_event
from yoke_core.domain import db_backend
from yoke_core.domain.migration_install_topology import (
    is_single_authoritative_install,
)
from yoke_core.domain.project_structure import read_structure


SKIP_MULTI_INSTALL = "multi_install_topology"
SKIP_INCOMPLETE = "modules_not_all_completed"
SKIP_GIT_UNAVAILABLE = "git_binary_unavailable"
SKIP_NOT_TRACKED = "module_file_not_in_git"
SKIP_FILE_ABSENT = "module_file_absent"
REMOVED_UNTRACKED = "removed_untracked_via_unlink"


def _every_module_completed(
    audit_conn: Any,
    *,
    model_name: str,
    module_identifiers: List[str],
) -> bool:
    if not module_identifiers:
        return False
    placeholder = "%s" if db_backend.connection_is_postgres(audit_conn) else "?"
    placeholders = ",".join(placeholder for _ in module_identifiers)
    rows = audit_conn.execute(
        f"SELECT migration_name "
        f"FROM migration_audit "
        f"WHERE model_name={placeholder} AND state='completed' "
        f"  AND migration_name IN ({placeholders})",
        (model_name, *module_identifiers),
    ).fetchall()
    completed = {str(r[0] if not hasattr(r, "keys") else r["migration_name"])
                 for r in rows}
    return all(name in completed for name in module_identifiers)


def _git_rm(
    worktree_path: Path, relative_target: Path,
) -> Dict[str, Any]:
    """Run ``git rm`` for a single relative target inside a worktree.

    Returns a structured outcome dict. Caller may aggregate multiple
    outcomes into a single audit payload.
    """
    if shutil.which("git") is None:
        return {
            "path": str(relative_target),
            "outcome": "skipped",
            "reason": SKIP_GIT_UNAVAILABLE,
        }
    abs_target = worktree_path / relative_target
    if not abs_target.exists():
        return {
            "path": str(relative_target),
            "outcome": "skipped",
            "reason": SKIP_FILE_ABSENT,
        }
    proc = subprocess.run(
        ["git", "-C", str(worktree_path), "rm", "-q", str(relative_target)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if "did not match any files" in stderr.lower():
            # File exists in the working tree but is not tracked by git
            # (a fresh migration module the slice authored but hadn't
            # committed before live-apply fired). git rm refuses; plain
            # unlink is safe because the file is by definition not in
            # the index or any prior commit.
            try:
                abs_target.unlink()
            except OSError as exc:
                return {
                    "path": str(relative_target),
                    "outcome": "failed",
                    "stderr": f"unlink fallback failed: {exc}",
                }
            return {
                "path": str(relative_target),
                "outcome": "removed",
                "reason": REMOVED_UNTRACKED,
            }
        return {
            "path": str(relative_target),
            "outcome": "failed",
            "stderr": stderr,
        }
    return {
        "path": str(relative_target),
        "outcome": "removed",
    }


def _candidate_targets(
    modules_dir_rel: Path,
    identifier: str,
    test_roots_rel: Iterable[Path] = (),
) -> List[Path]:
    """Return the per-module deletion candidates relative to worktree root.

    The module file always lives at ``<modules_dir>/<identifier>.py``.
    Test-file conventions vary by project; all known shapes are tried
    and the unused candidates skip cleanly with ``module_file_absent``:

    * ``<modules_dir>/test_<identifier>.py`` — tests-alongside-module.
    * ``<modules_dir>.parent/test_<identifier>.py`` — tests-one-level-up
      (matches Yoke's ``runtime/api/domain/test_<id>.py`` shape because
      ``runtime/api/domain/migrations``.parent is ``runtime/api/domain``).
    * ``<test_root>/test_<identifier>.py`` for each entry the caller
      sourced from ``project_structure.test_roots`` (matches a common
      ``app/tests/test_<id>.py`` shape and any project that
      declares its test trees there).
    """
    candidates: List[Path] = [
        modules_dir_rel / f"{identifier}.py",
        modules_dir_rel / f"test_{identifier}.py",
        modules_dir_rel.parent / f"test_{identifier}.py",
    ]
    seen = {str(c) for c in candidates}
    for test_root in test_roots_rel:
        relative = Path(test_root) / f"test_{identifier}.py"
        key = str(relative)
        if key in seen:
            continue
        candidates.append(relative)
        seen.add(key)
    return candidates


def _declared_test_roots(project: str) -> List[Path]:
    """Read project_structure.test_roots entries for the project.

    Failures are deliberately swallowed: the auto-retire is best-effort
    and a malformed or absent project_structure row must not block the
    canonical module-deletion path. An empty list collapses
    ``_candidate_targets`` back to the modules_dir-only shape.
    """
    try:
        structure = read_structure(project, family="test_roots")
    except Exception:  # noqa: BLE001 - best-effort read
        return []
    roots: List[Path] = []
    for entry in structure.get("entries", []) or []:
        attachment = entry.get("attachment")
        if not attachment:
            continue
        roots.append(Path(str(attachment).rstrip("/")))
    return roots


def auto_retire_after_live_apply(
    *,
    audit_conn: Any,
    project: str,
    model: Mapping[str, Any],
    profile: Mapping[str, Any],
    worktree_path: Path,
    modules_dir_rel: Path,
    item_id: int,
) -> Dict[str, Any]:
    """Retire migration modules in the worktree when topology allows.

    Returns a structured payload describing what was attempted and
    what fired. The payload is also emitted as a ``MigrationModuleRetired``
    or ``MigrationModuleRetireSkipped`` event for the audit trail.
    """
    module_identifiers = list(profile.get("migration_modules") or [])
    payload: Dict[str, Any] = {
        "project_id": project,
        "item_id": item_id,
        "model_name": str(profile.get("model_name") or ""),
        "modules": module_identifiers,
        "outcomes": [],
    }

    if not is_single_authoritative_install(model):
        payload["skipped"] = SKIP_MULTI_INSTALL
        emit_event(
            "MigrationModuleRetireSkipped",
            event_kind="lifecycle",
            event_type="migration_apply",
            source_type="backend",
            project=project,
            outcome="skipped",
            context=payload,
        )
        return payload

    if not _every_module_completed(
        audit_conn,
        model_name=payload["model_name"],
        module_identifiers=module_identifiers,
    ):
        payload["skipped"] = SKIP_INCOMPLETE
        emit_event(
            "MigrationModuleRetireSkipped",
            event_kind="lifecycle",
            event_type="migration_apply",
            source_type="backend",
            project=project,
            outcome="skipped",
            context=payload,
        )
        return payload

    test_roots_rel = _declared_test_roots(project)
    outcomes: List[Dict[str, Any]] = []
    for identifier in module_identifiers:
        for relative_target in _candidate_targets(
            modules_dir_rel, identifier, test_roots_rel,
        ):
            outcomes.append(_git_rm(worktree_path, relative_target))
    payload["outcomes"] = outcomes
    payload["staged_for_commit"] = any(
        o["outcome"] == "removed" for o in outcomes
    )
    emit_event(
        "MigrationModuleRetired",
        event_kind="lifecycle",
        event_type="migration_apply",
        source_type="backend",
        project=project,
        outcome="completed" if payload["staged_for_commit"] else "no_op",
        context=payload,
    )
    return payload


__all__ = [
    "REMOVED_UNTRACKED",
    "SKIP_FILE_ABSENT",
    "SKIP_GIT_UNAVAILABLE",
    "SKIP_INCOMPLETE",
    "SKIP_MULTI_INSTALL",
    "SKIP_NOT_TRACKED",
    "auto_retire_after_live_apply",
]

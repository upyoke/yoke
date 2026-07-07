"""Per-model validation surface provisioning for worktrees under the governed DB-mutation contract.

A ``mutation_intent="apply"`` ticket rehearses its migration on the
model's declared validation surface before the live-apply unit runs
against the authoritative DB. Yoke-project authority is Postgres and
its primary model declares ``external_validation``; this module provisions
only project-declared ``worktree_local_sqlite`` validation files, such as
webapp rehearsal DBs.

This module owns:

* :func:`provision_validation_surfaces` — for every declared model
  whose capability says ``validation_surface.kind = "worktree_local_sqlite"``
  in the worktree's project, ensure the validation file exists at the
  declared path and has been seeded by the configured provisioning
  recipe. Idempotent — returns a summary of what it found / created.

* :func:`resolve_validation_db_paths` — return the per-model
  ``{env_var, path}`` map implementation/test prompts surface so code
  running inside the worktree points at the validation target (by setting
  ``<runner.connection_env_var>=<validation-db-path>``) rather than the
  authoritative DB.

* :func:`prompt_env_var_bindings` — helper that returns the list of
  ``(env_var_name, path)`` tuples the implementation prompt should set
  in the command environment for worktree-local code and tests.
  ``CANONICAL_YOKE_DB`` (the control-plane token) is always present; one
  additional entry per declared model whose runner declares a
  ``connection_env_var``.

Control-plane separation: ``/yoke`` control-plane commands must continue to
mutate the canonical control-plane DB regardless of declared model.
Those commands resolve the control-plane token via the worktree resolver
(``resolve_db_path``) — this module only governs the
per-model connection env vars, not the control-plane one.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain.migration_model_capability import (
    CAPABILITY_TYPE as MIGRATION_MODEL_CAPABILITY_TYPE,
    DEFAULT_CONNECTION_ENV_VAR,
    MigrationModelCapabilityError,
    validate as validate_capability,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.schema_common_sqlite_validation import (
    _generic_sqlite_validation_table_exists,
)
from yoke_core.domain.sqlite_validation_boundary import (
    reject_retired_root_yoke_db_path,
)
from yoke_core.domain.worktree_validation_recipes import (
    RECIPE_WEBAPP_SQLITE_EMPTY,
    dispatch as dispatch_recipe,
)


CANONICAL_YOKE_DB_ENV = "CANONICAL_YOKE_DB"


@dataclass
class ProvisionedSurface:
    """Result summary for a single model's validation surface."""

    model_name: str
    kind: str
    env_var: str
    path: Path
    created: bool  # True when this call created the file; False when already present
    error: Optional[str] = None


@dataclass
class ProvisionResult:
    """Overall result of :func:`provision_validation_surfaces`."""

    project: str
    worktree_path: Path
    surfaces: List[ProvisionedSurface] = field(default_factory=list)

    @property
    def any_failures(self) -> bool:
        return any(s.error for s in self.surfaces)


# ---------------------------------------------------------------------------
# Capability lookup
# ---------------------------------------------------------------------------


def _load_capability(
    project: str, *, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        project_id = resolve_project_id(conn, project)
        raw = query_scalar(
            conn,
            "SELECT COALESCE(settings, '{}') FROM project_capabilities "
            f"WHERE project_id={marker} AND type={marker}",
            (project_id, MIGRATION_MODEL_CAPABILITY_TYPE),
        )
    finally:
        conn.close()
    if not raw:
        return None
    try:
        return validate_capability(json.loads(raw))
    except (json.JSONDecodeError, MigrationModelCapabilityError):
        return None


def _resolve_env_var(model: Mapping[str, Any]) -> str:
    runner = model.get("runner") or {}
    config = runner.get("config") or {}
    return str(config.get("connection_env_var") or DEFAULT_CONNECTION_ENV_VAR)


def _resolve_validation_path(
    worktree_path: Path, model: Mapping[str, Any]
) -> Optional[Path]:
    """Return the absolute validation-DB path for a model, or None if the
    model's validation surface is not ``worktree_local_sqlite``."""
    surface = model.get("validation_surface") or {}
    if surface.get("kind") != "worktree_local_sqlite":
        return None
    provisioning = surface.get("provisioning") or {}
    rel = provisioning.get("path") or ".yoke/validation.db"
    path = (worktree_path / rel).resolve()
    reject_retired_root_yoke_db_path(
        path, surface="worktree_local_sqlite validation surface",
    )
    return path


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _seed_validation_db(
    validation_db_path: Path,
    recipe: str,
    *,
    project: Optional[str] = None,
    model: Optional[str] = None,
    recipe_config: Optional[Mapping[str, Any]] = None,
) -> None:
    """Dispatch the configured *recipe* against *validation_db_path*.

    Routing the named recipe through
    :mod:`yoke_core.domain.worktree_validation_recipes` means the
    validation surface is project-configured. The live recipe today is
    ``webapp_sqlite_empty`` for external webapp SQLite validation; Yoke
    itself uses Postgres external validation and is not provisioned here.

    Unknown recipe names raise
    :class:`worktree_validation_recipes.UnknownValidationRecipe` with
    project/model context.
    """
    dispatch_recipe(
        recipe, validation_db_path, recipe_config,
        project=project, model=model,
    )


_SEED_MARKER_TABLES: Dict[str, str] = {
    # Webapp recipe: only the schema_version scaffolding is seeded by
    # the recipe; Python migration modules land schema content later.
    RECIPE_WEBAPP_SQLITE_EMPTY: "schema_version",
}


def _validation_db_already_seeded(path: Path, recipe: str) -> bool:
    """Return whether the validation DB carries the recipe marker table.

    Generic SQLite validation classification: the raw ``sqlite3`` connection
    below is deliberate and must survive bridge deletion. A
    ``worktree_local_sqlite`` validation surface genuinely IS an on-disk
    SQLite file (the rehearsal DB a project's migrations run against), and its
    catalog probe is routed through ``schema_common_sqlite_validation``. Contrast
    ``_load_capability`` above, which reads Yoke's own control plane through
    the backend factory (Postgres authority). Do not replace this with a
    Yoke-authority facade probe.
    """
    if not path.is_file():
        return False
    marker = _SEED_MARKER_TABLES.get(recipe)
    if marker is None:
        return False
    try:
        conn = sqlite3.connect(str(path))
    except sqlite3.Error:
        return False
    try:
        return _generic_sqlite_validation_table_exists(conn, marker)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def provision_validation_surfaces(
    worktree_path: Path | str,
    project: str,
    *,
    db_path: Optional[str] = None,
) -> ProvisionResult:
    """Ensure every declared model's validation surface exists under *worktree_path*.

    Idempotent: when a validation DB is already present and seeded, the
    call is a no-op and ``ProvisionedSurface.created`` is ``False`` for
    that model.

    Models whose capability declares a non-``worktree_local_sqlite``
    validation surface are skipped (no entry in the result).  The
    capability table not existing, or the project not declaring a
    migration_model capability, is a clean no-op (empty ``surfaces``).
    """
    wt_path = Path(worktree_path) if not isinstance(worktree_path, Path) else worktree_path
    result = ProvisionResult(project=project, worktree_path=wt_path)

    capability = _load_capability(project, db_path=db_path)
    if capability is None:
        return result

    models = capability.get("models") or {}
    for model_name, model in models.items():
        path = _resolve_validation_path(wt_path, model)
        if path is None:
            # Surface kind not in scope for worktree-local provisioning;
            # skip silently — future kinds (staging_db, ephemeral_container,
            # external_validation) land with their own provisioning hooks.
            continue
        env_var = _resolve_env_var(model)
        provisioning = (model.get("validation_surface") or {}).get("provisioning") or {}
        recipe = str(provisioning.get("recipe") or "")
        surface = ProvisionedSurface(
            model_name=str(model_name),
            kind="worktree_local_sqlite",
            env_var=env_var,
            path=path,
            created=False,
        )
        try:
            if _validation_db_already_seeded(path, recipe):
                surface.created = False
            else:
                _seed_validation_db(
                    path, recipe,
                    project=project, model=str(model_name),
                )
                surface.created = True
        except Exception as exc:  # noqa: BLE001 — surface as structured error
            surface.error = str(exc)
        result.surfaces.append(surface)

    return result


def resolve_validation_db_paths(
    worktree_path: Path | str,
    project: str,
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Dict[str, str]]:
    """Return the per-model ``{env_var, path}`` map for the worktree.

    Only models with ``validation_surface.kind = "worktree_local_sqlite"``
    appear in the result.  Useful for prompt surfacing and for tests
    that need to drive migrations against the validation DB without
    triggering full provisioning.
    """
    wt_path = Path(worktree_path) if not isinstance(worktree_path, Path) else worktree_path
    capability = _load_capability(project, db_path=db_path)
    if capability is None:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for model_name, model in (capability.get("models") or {}).items():
        path = _resolve_validation_path(wt_path, model)
        if path is None:
            continue
        out[str(model_name)] = {
            "env_var": _resolve_env_var(model),
            "path": str(path),
        }
    return out


def prompt_env_var_bindings(
    worktree_path: Path | str,
    project: str,
    *,
    canonical_db_path: str,
    db_path: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Bindings the implementation prompt should export.

    Returns the list of ``(env_var, value)`` tuples that pin the
    control-plane DB to its canonical path and each declared model's
    runner ``connection_env_var`` to the matching worktree-local
    validation DB.

    The first element is always ``(CANONICAL_YOKE_DB, canonical_db_path)``.
    Subsequent entries are added in declaration order by model name —
    one per model with a ``worktree_local_sqlite`` surface.

    The legacy ``YOKE_DB`` token is NOT pinned here. When a
    ``/yoke`` control-plane command runs, it resolves the control-plane token via
    :func:`yoke_core.domain.worktree.resolve_db_path` which walks up
    to the canonical state dir — the control plane is Yoke's
    regardless of which worktree initiated the command.
    """
    bindings: List[Tuple[str, str]] = [
        (CANONICAL_YOKE_DB_ENV, canonical_db_path),
    ]
    for _, meta in sorted(
        resolve_validation_db_paths(
            worktree_path, project, db_path=db_path,
        ).items()
    ):
        bindings.append((meta["env_var"], meta["path"]))
    return bindings


__all__ = [
    "CANONICAL_YOKE_DB_ENV",
    "ProvisionResult",
    "ProvisionedSurface",
    "prompt_env_var_bindings",
    "provision_validation_surfaces",
    "resolve_validation_db_paths",
]

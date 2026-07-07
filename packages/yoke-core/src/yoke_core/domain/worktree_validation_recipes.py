"""Validation surface provisioning recipe dispatch.

The split: **recipes are responsible for the validation surface; runners
are responsible for schema content.** A recipe creates the validation
target and any minimal scaffolding the runner relies on (e.g. a
``schema_version`` table); the runner then applies migrations against
that surface. A recipe never applies migrations; a runner never assumes
the surface contains baseline schema.

One recipe is wired today:

* ``webapp_sqlite_empty`` — empty SQLite file with the canonical
  webapp PRAGMA tuple (``journal_mode=WAL``, ``foreign_keys=ON``,
  ``busy_timeout=5000``) plus a ``schema_version`` table. The configured
  Python migration-module runner is then responsible for schema content.

Unknown recipe names raise :class:`UnknownValidationRecipe` at dispatch
time. The capability validator already refuses unknown values at
authoring time; the dispatch refusal is defense-in-depth.
"""

from __future__ import annotations

# Genuine generic-validation SQLite: this recipe seeds a project's
# worktree-local validation *surface* (an on-disk SQLite file the migration
# runner rehearses against), never Yoke's own control plane (Postgres
# authority). Keep this import — it is not Yoke-authority residue.
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional

from yoke_core.domain.migration_model_capability_validation import (
    RECIPE_WEBAPP_SQLITE_EMPTY,
)

_SCHEMA_VERSION_TABLE = "schema_version"

_KNOWN_RECIPES: FrozenSet[str] = frozenset({
    RECIPE_WEBAPP_SQLITE_EMPTY,
})


class UnknownValidationRecipe(ValueError):
    """Raised when a ``validation_surface.provisioning.recipe`` is unrecognized."""

    def __init__(
        self,
        recipe: Any,
        *,
        project: Optional[str] = None,
        model: Optional[str] = None,
        known_recipes: Optional[FrozenSet[str]] = None,
    ) -> None:
        self.recipe = recipe
        self.project = project
        self.model = model
        self.known_recipes = known_recipes or _KNOWN_RECIPES
        parts = [
            f"validation_surface.provisioning.recipe {recipe!r} is not registered",
        ]
        if project:
            parts.append(f"project={project!r}")
        if model:
            parts.append(f"model={model!r}")
        parts.append(f"known recipes: {sorted(self.known_recipes)}")
        super().__init__("; ".join(parts))


def known_recipes() -> FrozenSet[str]:
    return _KNOWN_RECIPES


def dispatch(
    recipe: str,
    validation_db_path: Path,
    recipe_config: Optional[Mapping[str, Any]] = None,
    *,
    project: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    """Run the seed callable for *recipe* against *validation_db_path*.

    *recipe_config* is reserved for future recipes that accept tunable
    parameters; today's recipes have no configurable knobs. *project*
    and *model* are passed through to :class:`UnknownValidationRecipe`
    so authors see the exact config to amend.
    """
    seeder = _RECIPES.get(recipe)
    if seeder is None:
        raise UnknownValidationRecipe(
            recipe, project=project, model=model, known_recipes=_KNOWN_RECIPES,
        )
    validation_db_path.parent.mkdir(parents=True, exist_ok=True)
    seeder(validation_db_path, recipe_config or {})


# ---------------------------------------------------------------------------
# Recipe implementations
# ---------------------------------------------------------------------------


def _recipe_webapp_sqlite_empty(
    validation_db_path: Path, _config: Mapping[str, Any]
) -> None:
    """Empty SQLite surface for webapp projects.

    Classification: genuine generic-validation SQLite — the live recipe for a
    webapp project (e.g. Buzz) whose own authoritative DB is SQLite. Kept
    regardless of Yoke's Postgres authority; validating external SQLite
    projects is a first-class capability, not residue.

    Creates the file (if missing) with the canonical PRAGMA tuple and a
    ``schema_version`` table the configured runner uses to track
    applied migrations. Crucially, this recipe does NOT apply any schema
    content — that work belongs to the configured runner during
    rehearsal/live-apply.
    """
    conn = sqlite3.connect(str(validation_db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_SCHEMA_VERSION_TABLE} ("
            " version INTEGER PRIMARY KEY,"
            " applied_at DATETIME DEFAULT (datetime('now'))"
            ")"
        )
        conn.commit()
    finally:
        conn.close()


_RECIPES: Dict[str, Callable[[Path, Mapping[str, Any]], None]] = {
    RECIPE_WEBAPP_SQLITE_EMPTY: _recipe_webapp_sqlite_empty,
}


__all__ = [
    "RECIPE_WEBAPP_SQLITE_EMPTY",
    "UnknownValidationRecipe",
    "dispatch",
    "known_recipes",
]

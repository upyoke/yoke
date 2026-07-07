"""Install topology for governed-migration models.

A model's **install topology** describes how many authoritative-DB
installs the migration must reach before its module can retire.

* **Single-install** — the model declares exactly one authoritative DB
  (one ``sqlite_file`` location, no fan-out). Once
  ``migration_audit.state='completed'`` lands on that one install, the
  migration is universally applied. Module retirement may happen in
  the same slice as live-apply.
* **Multi-install** — the model declares more than one authoritative
  DB (a future capability shape, e.g. a list under
  ``authoritative_db.installs``). Module retirement waits until every
  install has recorded ``state='completed'``; the cutover-ticket AC
  remains "retire in the post-merge slice" for these projects.

Today's `governed_migration_module` runner only ships single-install
support; the helper is forward-compatible so a future multi-install
schema flips it without a code change at every consumer site.

Consumers:

* The skill that drafts AC wording for migration tickets reads
  :func:`is_single_authoritative_install` to choose between the
  "retire in this slice" and "retire in the post-merge slice"
  templates.
* :mod:`yoke_core.domain.migration_apply` reads the helper after
  live-apply to decide whether to auto-retire the module file.
* :mod:`yoke_core.engines.doctor_hc_stranded_migrations` reads it
  to decide whether a still-present module file is stranded.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.migration_apply_resolve import (
    _resolve_capability_settings,
)
from yoke_core.domain.migration_model_capability_defaults import (
    resolve_model,
)


def is_single_authoritative_install(model: Mapping[str, Any]) -> bool:
    """Return True iff *model* declares exactly one authoritative DB.

    The check inspects ``model.authoritative_db``. Today that block
    carries a single ``location`` mapping. A future multi-install
    schema is expected to carry an explicit ``installs`` list (or a
    similar fan-out marker); when that lands, this helper returns
    False without any consumer-site edit.
    """
    auth = model.get("authoritative_db") or {}
    if not isinstance(auth, Mapping):
        return False
    installs = auth.get("installs")
    if isinstance(installs, list) and len(installs) > 1:
        return False
    location = auth.get("location") or {}
    if isinstance(location, list) and len(location) > 1:
        return False
    if isinstance(location, Mapping):
        if auth.get("kind") == "postgres":
            return bool(location.get("database_name"))
        return bool(location.get("path"))
    return False


def project_model_is_single_install(
    conn: Any, project: str, model_name: str,
) -> bool:
    """Resolve the named model for *project* and report install topology.

    Convenience wrapper that goes from ``(project, model_name)`` to
    the boolean answer in one call. Raises ``KeyError`` for an unknown
    model name and propagates ``MigrationApplyError`` for missing
    capability rows.
    """
    capability = _resolve_capability_settings(conn, project)
    model = resolve_model(capability, model_name)
    return is_single_authoritative_install(model)


__all__ = [
    "is_single_authoritative_install",
    "project_model_is_single_install",
]

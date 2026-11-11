"""Least-privilege identity a fleet preflight box uses to record its receipts.

A box that rehearses a migration fleet reads the covered environment's
release settings and, after the whole fleet passes, records its receipt under
``release.fleet_rehearsal`` on that environment. It does so as a project
service actor holding one machine-only project role, ``preflight_executor``,
which carries ``items.read`` and one narrow write permission. That permission
authorizes the generic environment-settings merge only when every assigned
path lies under ``release.fleet_rehearsal.``; any other key still needs
project administration (:mod:`yoke_core.domain.fleet_rehearsal_record_permission`).
"""

from __future__ import annotations

from yoke_core.domain.migration_preflight_receipt import SETTINGS_ROOT

ROLE_PREFLIGHT_EXECUTOR = "preflight_executor"
PERM_FLEET_REHEARSAL_RECORD = "release.fleet_rehearsal.record"
FLEET_REHEARSAL_MERGE_FUNCTION = "projects.environment_settings.merge"
#: Every path the narrow permission may assign starts with this prefix.
FLEET_REHEARSAL_PATH_PREFIX = f"{SETTINGS_ROOT}."

ROLE_PREFLIGHT_EXECUTOR_DESCRIPTION = (
    "Fleet preflight box: read release settings and record fleet rehearsal "
    "receipts; nothing else."
)
PERM_FLEET_REHEARSAL_RECORD_DESCRIPTION = (
    "Merge environment settings only under release.fleet_rehearsal.*."
)


def is_fleet_rehearsal_path(path: object) -> bool:
    """True when ``path`` names a leaf strictly inside the receipt namespace."""
    if not isinstance(path, str) or not path.startswith(FLEET_REHEARSAL_PATH_PREFIX):
        return False
    return all(path.split("."))


__all__ = [
    "FLEET_REHEARSAL_MERGE_FUNCTION",
    "FLEET_REHEARSAL_PATH_PREFIX",
    "PERM_FLEET_REHEARSAL_RECORD",
    "PERM_FLEET_REHEARSAL_RECORD_DESCRIPTION",
    "ROLE_PREFLIGHT_EXECUTOR",
    "ROLE_PREFLIGHT_EXECUTOR_DESCRIPTION",
    "is_fleet_rehearsal_path",
]

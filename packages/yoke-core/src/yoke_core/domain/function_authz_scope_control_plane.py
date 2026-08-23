"""Explicit authorization specs for whole-control-plane functions."""

from yoke_contracts.migration_content_identity import FUNCTION_ID
from yoke_core.domain.actor_permissions import PERM_DB_READ_RAW
from yoke_core.domain.function_authz_types import CONTROL_PLANE, AuthzSpec
from yoke_core.domain.migration_content_identity_authority import (
    PERM_MIGRATION_CONTENT_IDENTITY_VERIFY,
)


CONTROL_PLANE_AUTHZ_BY_ID = {
    "db.read.run": AuthzSpec(CONTROL_PLANE, PERM_DB_READ_RAW),
    "doctor.run.run": AuthzSpec(CONTROL_PLANE, PERM_DB_READ_RAW),
    "projects.github_sync_mode.repair": AuthzSpec(CONTROL_PLANE, PERM_DB_READ_RAW),
    FUNCTION_ID: AuthzSpec(CONTROL_PLANE, PERM_MIGRATION_CONTENT_IDENTITY_VERIFY),
}


__all__ = ["CONTROL_PLANE_AUTHZ_BY_ID"]

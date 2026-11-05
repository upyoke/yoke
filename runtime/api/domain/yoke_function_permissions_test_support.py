# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.function_permission_test_support import (
    _conn,
    _create_ephemeral_env_table,
    _entry,
    _read_entry,
    _process_acquire_request,
    _seed_session,
)

import pytest

from yoke_core.domain.actor_permissions import (
    PERM_CLAIMS_ACQUIRE,
    PERM_CLAIMS_RELEASE,
    PERM_DB_READ_RAW,
    PERM_EVENTS_READ,
    PERM_EVENTS_WRITE,
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    ROLE_OPERATOR,
    ROLE_OWNER,
    ROLE_VIEWER,
    PermissionDenied,
    grant_actor_project_role,
    require_permission,
)

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain.project_identity import resolve_project_id

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.yoke_function_permissions import (
    check_dispatch_permission,
    permission_key_for,
)

from yoke_core.domain.work_claim_targets import make_process_target

from yoke_core.domain.work_processes import PROCESS_DOCTOR

"""State, errors, and result contracts for governed migration apply."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from yoke_core.domain import db_helpers

STATE_PLANNED = "planned"
STATE_TEST_COPY_CREATED = "test_copy_created"
STATE_TEST_APPLIED = "test_applied"
STATE_TEST_VERIFIED = "test_verified"
STATE_REHEARSED = "rehearsed"
STATE_BACKUP_CREATED = "backup_created"
STATE_LIVE_APPLIED = "live_applied"
STATE_LIVE_VERIFIED = "live_verified"
STATE_COMPLETED = "completed"

FAIL_TEST_COPY = "test_copy_failed"
FAIL_TEST_APPLY = "test_apply_failed"
FAIL_TEST_VERIFY = "test_verify_failed"
FAIL_BACKUP = "backup_failed"
FAIL_LIVE_APPLY = "live_apply_failed"
FAIL_LIVE_VERIFY = "live_verify_failed"

LEASE_KEY_PREFIX = "LIVE_DB_MIGRATION:"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MigrationApplyError(Exception):
    """Base error for the two-unit apply contract."""


class ProfileNotApplyError(MigrationApplyError):
    """Raised when the ticket is not configured for the apply flow."""


class CompatibilityClassError(MigrationApplyError):
    """Raised when live-apply is requested for a non-safe compatibility class."""


class RehearsalStaleError(MigrationApplyError):
    """Fingerprint mismatch or freshness window expiry at live-apply promotion."""


class RehearsalMissingError(MigrationApplyError):
    """Live-apply invoked before a successful rehearsal landed."""


class ModuleResolutionError(MigrationApplyError):
    """Named migration module cannot be found or imported."""


class ModuleContractError(MigrationApplyError):
    """Imported module does not expose the expected ``apply(conn)`` surface."""


class ModuleOverrideError(MigrationApplyError):
    """Raised when ``--module-path-override`` fails the cross-worktree contract.

    The override sanctions importing a migration module from an active
    feature-worktree checkout instead of the main modules directory. Any
    denied shape — path outside the active item worktree, symlink escape,
    undeclared slug, basename mismatch, missing/inactive worktree scope,
    scope item mismatch — surfaces as this error so the CLI exits with a
    structured refusal.
    """


# ---------------------------------------------------------------------------
# Result dataclasses (operator-facing return shapes)
# ---------------------------------------------------------------------------


@dataclass
class ModuleAttemptResult:
    identifier: str
    audit_id: Optional[int]
    state: str
    error: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class RehearseResult:
    item_id: Optional[int]
    model_name: str
    validation_db_path: str
    source_fingerprint: Optional[str]
    rehearsed_at: Optional[str]
    modules: List[ModuleAttemptResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(m.succeeded for m in self.modules) and bool(self.modules)


@dataclass
class LiveApplyResult:
    item_id: Optional[int]
    model_name: str
    authoritative_db_path: str
    lease_id: Optional[int]
    modules: List[ModuleAttemptResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(m.succeeded for m in self.modules) and bool(self.modules)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return db_helpers.iso8601_now()


def _safe_parse_json_dict(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}



__all__ = [
    "STATE_PLANNED",
    "STATE_TEST_COPY_CREATED",
    "STATE_TEST_APPLIED",
    "STATE_TEST_VERIFIED",
    "STATE_REHEARSED",
    "STATE_BACKUP_CREATED",
    "STATE_LIVE_APPLIED",
    "STATE_LIVE_VERIFIED",
    "STATE_COMPLETED",
    "FAIL_TEST_COPY",
    "FAIL_TEST_APPLY",
    "FAIL_TEST_VERIFY",
    "FAIL_BACKUP",
    "FAIL_LIVE_APPLY",
    "FAIL_LIVE_VERIFY",
    "LEASE_KEY_PREFIX",
    "MigrationApplyError",
    "ProfileNotApplyError",
    "CompatibilityClassError",
    "RehearsalStaleError",
    "RehearsalMissingError",
    "ModuleResolutionError",
    "ModuleContractError",
    "ModuleOverrideError",
    "ModuleAttemptResult",
    "RehearseResult",
    "LiveApplyResult",
    "_now",
    "_safe_parse_json_dict",
]

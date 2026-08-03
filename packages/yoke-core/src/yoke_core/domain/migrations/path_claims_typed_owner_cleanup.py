"""Drop the legacy path-claim identity columns replaced by typed owners."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migrations.obsolete_schema_cleanup import (
    apply_path_claims_typed_owner_cleanup,
    verify_path_claims_typed_owner_cleanup,
)

MIGRATION_NAME = "path_claims_typed_owner_cleanup"


def apply(conn: Any) -> None:
    apply_path_claims_typed_owner_cleanup(conn)


def invariants(conn: Any) -> None:
    verify_path_claims_typed_owner_cleanup(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]

"""Outside projects can call the migration kernel with a named restore point."""

from pathlib import Path

import pytest

from runtime.api.domain.migration_boot_test_helpers import (
    RESTORE_POINT,
    applied_names,
    connection,
    history,
    marks,
)
from yoke_core.domain import administered_postgres, migration_boot_apply
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT

ATTRIBUTION = {
    "session_id": "external-session",
    "actor_id": "external-actor",
    "source_branch": "main",
    "source_commit": "external-commit",
}


@pytest.mark.parametrize("operation", ["stamp", "apply"])
def test_outside_caller_resolves_authority_from_connection(
    tmp_path: Path,
    monkeypatch,
    operation: str,
) -> None:
    conn = connection()
    entries = history(tmp_path, "0001_first")
    resolved_connections = []
    authorities = []

    def resolve(*, connection):
        resolved_connections.append(connection)
        return "external-db-admin"

    monkeypatch.setattr(administered_postgres, "administering_target", resolve)
    monkeypatch.setattr(
        migration_boot_apply,
        "refuse_without_serving_build_authority",
        lambda action, *, administering_env: authorities.append(administering_env),
    )

    if operation == "stamp":
        stamped = migration_boot_apply.stamp_history(
            conn,
            entries,
            ledger=YOKE_LEDGER_CONTRACT,
            applied_by="platform-registry-birth",
        )
        assert stamped == ("0001_first",)
        assert marks(conn) == []
    else:
        outcome = migration_boot_apply.apply_pending(
            conn,
            history=entries,
            ledger=YOKE_LEDGER_CONTRACT,
            applied_by="external-registry",
            running_version="",
            attribution=ATTRIBUTION,
            model_name="registry",
            external_restore_point=RESTORE_POINT,
        )
        assert outcome.applied == ("0001_first",)
        assert outcome.restore_point == RESTORE_POINT
        assert marks(conn) == ["0001_first"]

    assert applied_names(conn) == {"0001_first"}
    assert resolved_connections == [conn]
    assert authorities == ["external-db-admin"]


@pytest.mark.parametrize("operation", ["stamp", "apply"])
def test_explicit_authority_does_not_resolve_from_connection(
    monkeypatch,
    operation: str,
) -> None:
    def unexpected_resolution(**kwargs):
        pytest.fail("an explicit authority must stay authoritative")

    monkeypatch.setattr(
        administered_postgres,
        "administering_target",
        unexpected_resolution,
    )
    conn = connection()
    if operation == "stamp":
        assert (
            migration_boot_apply.stamp_history(
                conn,
                (),
                ledger=YOKE_LEDGER_CONTRACT,
                applied_by="external-registry",
                administering_env="",
            )
            == ()
        )
    else:
        assert not migration_boot_apply.apply_pending(
            conn,
            history=(),
            ledger=YOKE_LEDGER_CONTRACT,
            applied_by="external-registry",
            administering_env="",
            running_version="",
            attribution={},
            model_name="registry",
        ).changed

"""Transaction ownership coverage for backlog mutation gates."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_backlog_updates_helpers import _EXTRA_DDL
from runtime.api.fixtures.backlog import SCHEMA_DDL, insert_item
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import db_mutation_gate
from yoke_core.domain.backlog_updates_helpers import _run_db_mutation_gate
from yoke_core.domain.schema_init_apply import execute_schema_script


@pytest.fixture
def helper_db(tmp_path: Path):
    db_file = tmp_path / "yoke.db"
    conn = connect_test_db(str(db_file))
    execute_schema_script(conn, SCHEMA_DDL)
    execute_schema_script(conn, _EXTRA_DDL)
    conn.commit()
    yield conn, str(db_file)
    conn.close()


def test_parent_transaction_owns_declared_attestation_freeze(
    helper_db,
    monkeypatch,
) -> None:
    conn, db_path = helper_db
    declared_profile = {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply",
        "migration_modules": ["m"],
        "compatibility_class": "pre_merge_breaking",
        "migration_strategy": "expand_contract",
    }
    insert_item(
        conn,
        id=22,
        status="idea",
        db_mutation_profile=json.dumps(declared_profile, sort_keys=True),
        db_compatibility_attestation="{}",
    )
    monkeypatch.setattr(
        db_mutation_gate,
        "check_idea_to_refining_idea_gate",
        lambda *_args, **_kwargs: SimpleNamespace(
            passed=True,
            errors=[],
            warnings=[],
            escalations=[],
        ),
    )

    assert (
        _run_db_mutation_gate(
            item_id=22,
            target_status="refining-idea",
            db_path=db_path,
            conn=conn,
        )
        is None
    )
    in_transaction = json.loads(
        conn.execute(
            "SELECT db_compatibility_attestation FROM items WHERE id=22"
        ).fetchone()[0]
    )
    assert in_transaction["frozen_at"].endswith("Z")

    conn.rollback()
    persisted = json.loads(
        conn.execute(
            "SELECT db_compatibility_attestation FROM items WHERE id=22"
        ).fetchone()[0]
    )
    assert "frozen_at" not in persisted

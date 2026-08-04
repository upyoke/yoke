"""The rehearsal-failure remediation quotes a rendered public item ref.

``issue_payloads_for_item`` prints a ``yoke db-claim amend <ref>`` command an
operator is expected to paste. Building that ref inline from the internal
``items.id`` would be wrong twice over: it hardcodes one project's prefix, and
it prints the storage id instead of the project sequence the operator sees.

Every fixture here uses a project whose ``public_item_prefix`` is NOT ``YOK``
and whose ``project_sequence`` differs from ``items.id``, so a prefix literal
or an internal id cannot pass.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from yoke_core.domain.attestation_rehearsal_dryrun import issue_payloads_for_item
from yoke_core.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)

_FROZEN_AT = "2026-05-20T17:00:00Z"


@pytest.fixture
def conn():
    conn = connect_disposable_test_db()
    conn.execute(
        "CREATE TABLE items ("
        "id INTEGER PRIMARY KEY, project_id INTEGER, project_sequence INTEGER, "
        "db_mutation_profile TEXT, db_compatibility_attestation TEXT)"
    )
    conn.execute(
        "CREATE TABLE projects ("
        "id INTEGER PRIMARY KEY, slug TEXT, public_item_prefix TEXT)"
    )
    conn.execute(
        "INSERT INTO projects (id, slug, public_item_prefix) "
        "VALUES (7, 'buzzer', 'BUZ')"
    )
    conn.commit()
    yield conn
    conn.close()


def _seed(conn: Any, *, item_id: int, project_sequence: int, commands: List[str]):
    profile: Dict[str, Any] = {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply",
        "migration_modules": ["dummy_module"],
    }
    attestation: Dict[str, Any] = {
        "frozen_at": _FROZEN_AT,
        "pre_merge_readers_writers": "n/a",
        "invariants": "n/a",
        "rehearsal_commands": list(commands),
        "residual_risk_notes": "n/a",
    }
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence, "
        "db_mutation_profile, db_compatibility_attestation) "
        "VALUES (%s, %s, %s, %s, %s)",
        (item_id, 7, project_sequence, json.dumps(profile), json.dumps(attestation)),
    )
    conn.commit()


class TestRemediationUsesRenderedRef:
    def test_remediation_names_the_projects_prefix_and_sequence(self, conn) -> None:
        _seed(
            conn,
            item_id=4101,
            project_sequence=12,
            commands=["echo <unresolved>/path/to/anything.py"],
        )
        payloads = issue_payloads_for_item(conn, 4101)
        assert len(payloads) == 1
        remediation = payloads[0]["remediation"]
        assert "yoke db-claim amend BUZ-12 --reason" in remediation
        assert "YOK-" not in remediation
        assert "4101" not in remediation

    def test_every_failing_command_shares_the_one_rendered_ref(self, conn) -> None:
        _seed(
            conn,
            item_id=4102,
            project_sequence=13,
            commands=[
                "echo <unresolved>/one.py",
                "echo <alsounresolved>/two.py",
            ],
        )
        payloads = issue_payloads_for_item(conn, 4102)
        assert len(payloads) == 2
        for payload in payloads:
            assert "yoke db-claim amend BUZ-13 --reason" in payload["remediation"]
            assert "YOK-" not in payload["remediation"]

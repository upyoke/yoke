"""Deployment receipt schema, digest, and explicit archive read tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import deployment_receipts


FLOW_ID = "retired-prod-flow"
RUN_ID = "run-archive-001"
NOW = "2026-07-16T12:00:00Z"


def _flow_payload() -> dict:
    return {
        "definition_observed_at": NOW,
        "flow": {
            "id": FLOW_ID,
            "name": "Retired production flow",
            "project_id": 3,
            "stages": '[{"name":"deploy"}]',
        },
    }


def _run_payload() -> dict:
    return {
        "flow_receipt_id": FLOW_ID,
        "items": [],
        "preview_environments": [],
        "qa_requirements": [],
        "run": {
            "id": RUN_ID,
            "flow": FLOW_ID,
            "project_id": 3,
            "status": "succeeded",
        },
        "run_qa": [],
    }


def _insert_flow_receipt(conn, *, digest: str | None = None) -> None:
    payload, calculated = deployment_receipts.receipt_storage_values(
        _flow_payload()
    )
    conn.execute(
        "INSERT INTO deployment_flow_receipts "
        "(flow_id, project_id_snapshot, project_slug_snapshot, "
        "definition_observed_at, receipt_schema, payload, payload_sha256, "
        "archived_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            FLOW_ID, 3, "platform", NOW,
            deployment_receipts.FLOW_RECEIPT_SCHEMA,
            payload, digest or calculated, NOW,
        ),
    )


def _insert_run_receipt(conn, *, digest: str | None = None) -> None:
    payload, calculated = deployment_receipts.receipt_storage_values(
        _run_payload()
    )
    conn.execute(
        "INSERT INTO deployment_run_receipts "
        "(run_id, project_id_snapshot, project_slug_snapshot, flow_id, "
        "target_env, status, run_created_at, receipt_schema, payload, "
        "payload_sha256, archived_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            RUN_ID, 3, "platform", FLOW_ID, "prod", "succeeded", NOW,
            deployment_receipts.RUN_RECEIPT_SCHEMA,
            payload, digest or calculated, NOW,
        ),
    )


def test_canonical_digest_is_key_order_independent() -> None:
    first = {"run": {"id": RUN_ID, "status": "succeeded"}, "items": []}
    second = {"items": [], "run": {"status": "succeeded", "id": RUN_ID}}
    assert deployment_receipts.canonical_receipt_payload(first) == (
        deployment_receipts.canonical_receipt_payload(second)
    )
    assert deployment_receipts.deployment_receipt_digest(first) == (
        deployment_receipts.deployment_receipt_digest(second)
    )


def test_digest_verification_rejects_modified_payload() -> None:
    payload, digest = deployment_receipts.receipt_storage_values(_run_payload())
    modified = payload.replace("succeeded", "failed")
    with pytest.raises(
        deployment_receipts.DeploymentReceiptIntegrityError,
        match="digest does not match",
    ):
        deployment_receipts.verify_deployment_receipt(modified, digest)


def test_schema_converges_receipts_without_active_definitions(
    tmp_path: Path,
) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=current_schema()"
            ).fetchall()
        }
        assert "deployment_flow_receipts" in tables
        assert "deployment_run_receipts" in tables
        assert "deployment_flows" not in tables
        assert "deployment_runs" not in tables
        _insert_flow_receipt(conn)
        _insert_run_receipt(conn)
        conn.commit()
        conn.close()

        flow = deployment_receipts.get_flow_receipt(FLOW_ID, db_path=db_path)
        run = deployment_receipts.get_run_receipt(RUN_ID, db_path=db_path)

    assert flow is not None and flow["digest_verified"] is True
    assert flow["payload"]["flow"]["id"] == FLOW_ID
    assert run is not None and run["digest_verified"] is True
    assert run["payload"]["run"]["id"] == RUN_ID


@pytest.mark.parametrize(
    ("table", "id_column", "identifier"),
    (
        ("deployment_flow_receipts", "flow_id", FLOW_ID),
        ("deployment_run_receipts", "run_id", RUN_ID),
    ),
)
def test_receipt_rows_reject_update_and_delete(
    tmp_path: Path,
    table: str,
    id_column: str,
    identifier: str,
) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        _insert_flow_receipt(conn)
        _insert_run_receipt(conn)
        conn.commit()

        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                f"UPDATE {table} SET archived_at=%s WHERE {id_column}=%s",
                ("2026-07-17T00:00:00Z", identifier),
            )
        conn.rollback()

        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                f"DELETE FROM {table} WHERE {id_column}=%s", (identifier,)
            )
        conn.rollback()
        remaining = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {id_column}=%s",
            (identifier,),
        ).fetchone()[0]
        conn.close()
    assert remaining == 1


@pytest.mark.parametrize(
    "table", ("deployment_flow_receipts", "deployment_run_receipts")
)
def test_receipt_tables_reject_truncate(tmp_path: Path, table: str) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        _insert_flow_receipt(conn)
        _insert_run_receipt(conn)
        conn.commit()
        with pytest.raises(Exception, match="append-only"):
            conn.execute(f"TRUNCATE TABLE {table}")
        conn.rollback()
        remaining = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.close()
    assert remaining == 1


def test_list_filters_and_verifies_receipts(tmp_path: Path) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        _insert_flow_receipt(conn)
        _insert_run_receipt(conn)
        conn.commit()
        conn.close()

        flows = deployment_receipts.list_flow_receipts(
            project="platform", db_path=db_path
        )
        runs = deployment_receipts.list_run_receipts(
            project="platform", flow=FLOW_ID, status="succeeded",
            db_path=db_path,
        )
        no_runs = deployment_receipts.list_run_receipts(
            project="yoke", db_path=db_path
        )

    assert [row["flow_id"] for row in flows] == [FLOW_ID]
    assert [row["run_id"] for row in runs] == [RUN_ID]
    assert no_runs == []


def test_read_rejects_stored_digest_mismatch(tmp_path: Path) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        _insert_run_receipt(conn, digest="0" * 64)
        conn.commit()
        conn.close()
        with pytest.raises(
            deployment_receipts.DeploymentReceiptIntegrityError,
            match="digest does not match",
        ):
            deployment_receipts.get_run_receipt(RUN_ID, db_path=db_path)


def test_schema_rejects_unknown_receipt_version(tmp_path: Path) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        payload, digest = deployment_receipts.receipt_storage_values(
            _run_payload()
        )
        with pytest.raises(
            Exception,
            match="deployment_run_receipts_receipt_schema_check",
        ):
            conn.execute(
                "INSERT INTO deployment_run_receipts "
                "(run_id, project_id_snapshot, project_slug_snapshot, flow_id, "
                "target_env, status, run_created_at, receipt_schema, payload, "
                "payload_sha256, archived_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    RUN_ID, 3, "platform", FLOW_ID, "prod", "succeeded", NOW,
                    "unsupported/v9", payload, digest, NOW,
                ),
            )
        conn.rollback()
        conn.close()

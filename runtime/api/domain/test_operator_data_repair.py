"""Transactional row repairs preserve exact reviewed values and durable outcomes."""

from runtime.api.domain.operator_data_repair_test_support import (
    conn as conn,
    execute as execute,
    receipt as receipt,
)


import hashlib
import json

import pytest

from yoke_core.domain import operator_data_repair as repair
from yoke_core.domain.operator_data_repair_sql import RepairRefusal


def plan(**overrides):
    values = dict(
        project="alpha",
        sql="UPDATE repair_documents SET document='new' WHERE id=1",
        table="repair_documents",
        key_columns=["id"],
        before=[{"id": 1, "document": "old"}],
        after=[{"id": 1, "document": "new"}],
        reason="Reviewed invalid diagnostic document",
    )
    values.update(overrides)
    return repair.RepairPlan(**values)


def values(conn):
    return conn.execute(
        "SELECT id, document FROM public.repair_documents ORDER BY id"
    ).fetchall()


def test_commits_repair_and_exact_audit_together(conn):
    document = plan()
    result = execute(conn, document)
    assert result["outcome"] == "completed"
    assert values(conn) == [(1, "new"), (2, "unrelated")]
    row = receipt(conn)
    assert row[0] == "completed"
    assert row[1] == hashlib.sha256(document.sql.encode()).hexdigest()
    assert json.loads(row[2])["expected_before"] == document.before
    assert json.loads(row[2])["project"] == "alpha"
    assert json.loads(row[3]) == {
        "observed_before": document.before,
        "observed_after": document.after,
    }
    assert row[5] == "2"


def test_dry_run_simulates_real_sql_and_rolls_back_rows(conn):
    result = execute(conn, plan(), dry_run=True)
    assert result["outcome"] == "dry_run_rolled_back"
    assert values(conn) == [(1, "old"), (2, "unrelated")]
    assert receipt(conn)[0] == "test_verified"
    assert json.loads(receipt(conn)[3])["observed_after"] == plan().after


@pytest.mark.parametrize(
    "document,code",
    [
        (plan(before=[{"id": 1, "document": "stale"}]), "repair_before_changed"),
        (plan(after=[{"id": 1, "document": "wrong"}]), "repair_after_mismatch"),
        (
            plan(sql="UPDATE repair_documents SET document='new' WHERE id>0"),
            "repair_before_changed",
        ),
    ],
)
def test_failed_guards_roll_back_and_record_observed_rows(conn, document, code):
    with pytest.raises(RepairRefusal) as refused:
        execute(conn, document)
    assert refused.value.code == code
    assert values(conn) == [(1, "old"), (2, "unrelated")]
    assert receipt(conn)[0] == "live_apply_failed"
    assert code in receipt(conn)[4]


def test_delete_captures_deleted_rows(conn):
    document = plan(sql="DELETE FROM repair_documents WHERE id=1", after=[])
    execute(conn, document)
    assert values(conn) == [(2, "unrelated")]
    assert json.loads(receipt(conn)[3])["observed_before"] == document.before
    assert json.loads(receipt(conn)[3])["observed_after"] == []


def test_predicate_json_braces_do_not_become_composition_placeholders(conn):
    execute(
        conn,
        plan(
            sql="UPDATE repair_documents SET document='new' WHERE id=1 AND '{}'::jsonb='{}'::jsonb"
        ),
    )
    assert values(conn)[0] == (1, "new")


def test_json_document_repair_uses_postgres_parser_and_real_functions(conn):
    conn.execute(
        "UPDATE repair_documents SET document=%s WHERE id=1",
        ('{"diagnostic_expires_at":47}',),
    )
    conn.commit()
    document = plan(
        sql="UPDATE repair_documents SET document=(document::jsonb - 'diagnostic_expires_at')::text WHERE id=1",
        before=[{"id": 1, "document": '{"diagnostic_expires_at":47}'}],
        after=[{"id": 1, "document": "{}"}],
    )
    execute(conn, document)
    assert values(conn)[0] == (1, "{}")


def test_no_mutation_if_audit_cannot_be_started(conn, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(repair.audit, "begin", unavailable)
    with pytest.raises(RuntimeError):
        execute(conn, plan())
    assert values(conn)[0] == (1, "old")


def test_outcome_write_failure_rolls_back_mutation(conn, monkeypatch):
    original = repair.audit.finish

    def fail_success(connection, audit_id, **kwargs):
        if kwargs["state"] == "completed":
            raise RuntimeError("audit write unavailable")
        return original(connection, audit_id, **kwargs)

    monkeypatch.setattr(repair.audit, "finish", fail_success)
    with pytest.raises(RepairRefusal, match="repair_execution_failed|Audit"):
        execute(conn, plan())
    assert values(conn)[0] == (1, "old")
    assert receipt(conn)[0] == "live_apply_failed"


def test_crash_after_attempt_leaves_a_visible_planned_audit(conn, monkeypatch):
    def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(repair, "_table_contract", interrupted)
    with pytest.raises(KeyboardInterrupt):
        execute(conn, plan())
    conn.rollback()
    assert values(conn)[0] == (1, "old")
    assert receipt(conn)[0] == "planned"


def test_trigger_effects_are_refused_before_any_mutation(conn):
    conn.execute(
        "CREATE FUNCTION repair_trigger() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$"
    )
    conn.execute(
        "CREATE TRIGGER repair_effect BEFORE UPDATE ON repair_documents FOR EACH ROW EXECUTE FUNCTION repair_trigger()"
    )
    conn.commit()
    with pytest.raises(RepairRefusal) as refused:
        execute(conn, plan())
    assert refused.value.code == "repair_table_effects_refused"
    assert values(conn)[0] == (1, "old")


def test_sensitive_observed_values_cannot_pass_as_redacted_guards(conn):
    conn.execute(
        "UPDATE repair_documents SET document=%s WHERE id=1",
        ('{"secret":"actual-secret"}',),
    )
    conn.commit()
    document = plan(before=[{"id": 1, "document": '{"secret":"<redacted>"}'}])
    # The reviewed document itself refuses sensitive keys, and bypassing that
    # validation still cannot turn a redacted observation into exact proof.
    with pytest.raises(RepairRefusal) as refused:
        repair._snapshot(conn, document, ["id", "document"], "id=1")
    assert refused.value.code == "repair_sensitive_evidence"


def test_lost_commit_acknowledgement_reports_uncertainty(conn):
    class LostAcknowledgement:
        def __init__(self, inner):
            self.inner = inner
            self.commits = 0

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self):
            self.inner.commit()
            self.commits += 1
            if self.commits == 2:
                raise ConnectionError("lost acknowledgement after commit")

    with pytest.raises(RepairRefusal) as refused:
        execute(LostAcknowledgement(conn), plan())
    assert refused.value.code == "repair_commit_outcome_unknown"
    assert receipt(conn)[0] == "completed"
    assert values(conn)[0] == (1, "new")


@pytest.mark.parametrize(
    "owner,code", [(1, None), (2, "repair_project_scope_mismatch")]
)
def test_project_owned_rows_must_belong_to_the_document_project(conn, owner, code):
    conn.execute(
        "CREATE TABLE repair_owned (id integer PRIMARY KEY, project_id integer, note text)"
    )
    conn.execute("INSERT INTO repair_owned VALUES (1, %s, 'old')", (owner,))
    conn.commit()
    document = plan(
        sql="UPDATE repair_owned SET note='new' WHERE id=1",
        table="repair_owned",
        before=[{"id": 1, "project_id": owner, "note": "old"}],
        after=[{"id": 1, "project_id": owner, "note": "new"}],
    )
    if code is None:
        assert execute(conn, document)["outcome"] == "completed"
        return
    with pytest.raises(RepairRefusal) as refused:
        execute(conn, document)
    assert refused.value.code == code
    assert conn.execute("SELECT note FROM repair_owned").fetchone()[0] == "old"

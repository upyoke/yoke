"""Permanent conversion preflights owned documents and dependent projections."""

import importlib
import json

import pytest

from yoke_contracts.schema_authority import SchemaAuthorityRefused
from yoke_contracts.timestamps import format_instant
from yoke_core.domain import stored_instant_conversion as scalar
from yoke_core.domain.migrations import _native_instant_documents as documents
from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

history = importlib.import_module(
    "yoke_core.domain.migrations.0067_native_domain_instants"
)
STAMP = "2026-10-08T16:30:00.123456Z"


@pytest.fixture
def blank():
    from runtime.api.fixtures.native_instant_database import blank_database

    with blank_database() as conn:
        yield conn


def test_history_freezes_complete_roster_and_serving_floor():
    assert len(history.COLUMNS) == len(set(history.COLUMNS)) == 264
    assert len({table for table, _ in history.COLUMNS}) == 125
    assert set(history.COLUMNS) == set(STORED_INSTANT_COLUMNS)
    assert history.MINIMUM_SERVING_VERSION == "next-release"


def test_history_authority_refusal_precedes_document_reads(monkeypatch):
    class Unused:
        def execute(self, *args):
            pytest.fail("history read or changed administered database")

    monkeypatch.setattr(
        history.administered_postgres,
        "administering_target",
        lambda **_: "admin-target",
    )
    with pytest.raises(SchemaAuthorityRefused):
        history.apply(Unused())


def _owners(conn):
    conn.execute(
        "CREATE TABLE harness_sessions (session_id text PRIMARY KEY, "
        "vendor_resume_episode_key text, usage_totals text, "
        "last_tool_call_at text, last_heartbeat text)"
    )
    conn.execute(
        "CREATE TABLE deployment_runs (id integer PRIMARY KEY, "
        "driver_attachment text, started_at text, created_at text, "
        "current_stage_entered_at text)"
    )
    conn.execute(
        "CREATE TABLE qa_plan_executions (id integer PRIMARY KEY, "
        "release_reason text, created_at text)"
    )
    conn.execute(
        "CREATE TABLE decision_requests (id integer PRIMARY KEY, "
        "kind text, subject_context text, resolved_at text, "
        "withdrawn_at text, created_at text)"
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_owned_repairs_native_storage_opaque_facts_and_idempotence(blank, zone):
    conn = blank
    _owners(conn)
    conn.execute("SELECT set_config('TimeZone',%s,true)", (zone,))
    opaque = {"tokens": 9007199254740993, "note": "2020-01-01T00:00:00Z"}
    conn.execute(
        "INSERT INTO harness_sessions VALUES (%s,%s,%s,%s,%s)",
        ("s", "broken", json.dumps(opaque), STAMP, STAMP),
    )
    driver = dict(
        opaque, attached_at="2026-10-08 16:30:00.1234569", heartbeat_at="broken"
    )
    conn.execute(
        "INSERT INTO deployment_runs VALUES (1,%s,%s,%s,%s)",
        (json.dumps(driver), STAMP, STAMP, STAMP),
    )
    conn.execute(
        "INSERT INTO qa_plan_executions VALUES (1,%s,%s)",
        (json.dumps(dict(opaque, kind="qa_host_wait", queued_at="broken")), STAMP),
    )
    conn.execute(
        "INSERT INTO qa_plan_executions VALUES (2,'operator prose',%s)", (STAMP,)
    )
    context = dict(opaque, ended_at="", occurred_at="broken", expires_at="2026-10-08")
    conn.execute(
        "INSERT INTO decision_requests VALUES (1,'machine_approval',%s,NULL,NULL,%s)",
        (json.dumps(context), STAMP),
    )
    conn.execute(
        "INSERT INTO decision_requests VALUES (2,'human',%s,NULL,NULL,%s)",
        (json.dumps(context), STAMP),
    )
    before = conn.execute("SELECT driver_attachment FROM deployment_runs").fetchone()[0]
    updates = documents.prepare_document_updates(conn)
    assert len(updates) == 5
    assert (
        conn.execute("SELECT driver_attachment FROM deployment_runs").fetchone()[0]
        == before
    )
    history.apply(conn)
    history.invariants(conn)
    history.apply(conn)
    assert documents.prepare_document_updates(conn) == []
    episode, usage, last_call = conn.execute(
        "SELECT vendor_resume_episode_key,usage_totals,last_tool_call_at FROM harness_sessions"
    ).fetchone()
    assert episode == STAMP
    assert json.loads(usage) == dict(opaque, observed_at=None)
    assert format_instant(last_call) == STAMP
    stored = json.loads(
        conn.execute("SELECT driver_attachment FROM deployment_runs").fetchone()[0]
    )
    assert stored == dict(opaque, attached_at=STAMP, heartbeat_at=STAMP)
    reasons = conn.execute(
        "SELECT release_reason FROM qa_plan_executions ORDER BY id"
    ).fetchall()
    assert json.loads(reasons[0][0]) == dict(
        opaque, kind="qa_host_wait", queued_at=STAMP
    )
    assert reasons[1][0] == "operator prose"
    contexts = conn.execute(
        "SELECT subject_context FROM decision_requests ORDER BY id"
    ).fetchall()
    assert json.loads(contexts[0][0]) == dict(
        opaque,
        ended_at=None,
        occurred_at=STAMP,
        expires_at="2026-10-08T00:00:00.000000Z",
    )
    assert contexts[1][0] == json.dumps(context)


def test_unusable_document_owner_refuses_before_scalar_ddl(blank):
    _owners(blank)
    blank.execute("INSERT INTO deployment_runs VALUES (1,'{}',NULL,'broken',NULL)")
    with pytest.raises(RuntimeError, match="instant_document_owner_fact_unavailable"):
        history.apply(blank)
    assert (
        blank.execute(
            "SELECT data_type FROM information_schema.columns WHERE "
            "table_name='deployment_runs' AND column_name='created_at'"
        ).fetchone()[0]
        == "text"
    )
    assert (
        blank.execute("SELECT driver_attachment FROM deployment_runs").fetchone()[0]
        == "{}"
    )


def test_document_compare_and_set_refuses_newer_owner_facts(blank):
    _owners(blank)
    blank.execute(
        "INSERT INTO harness_sessions VALUES ('s','',%s,%s,%s)",
        ('{"observed_at": "2026-10-08"}', STAMP, STAMP),
    )
    updates = documents.prepare_document_updates(blank)
    blank.execute("UPDATE harness_sessions SET usage_totals='{}'")
    with pytest.raises(RuntimeError, match="instant_document_changed"):
        documents.apply_document_updates(blank, updates)
    assert (
        blank.execute("SELECT usage_totals FROM harness_sessions").fetchone()[0] == "{}"
    )


def _view_fixture(conn, name="item_progress_view"):
    conn.execute(
        "CREATE TABLE projection_clock (id integer PRIMARY KEY, observed_at text)"
    )
    conn.execute(
        "INSERT INTO projection_clock VALUES (1,'2026-10-08T16:30:00.1234569Z')"
    )
    conn.execute(f"CREATE VIEW {name} AS SELECT id,observed_at FROM projection_clock")


def test_owned_view_is_reconstructed_in_conversion_transaction(blank, monkeypatch):
    from yoke_core.domain import flow_init

    _view_fixture(blank)
    restored = []

    def rebuild(conn, *, commit):
        assert commit is False
        conn.execute(
            "CREATE VIEW item_progress_view AS SELECT id,observed_at FROM projection_clock"
        )
        restored.append(True)

    monkeypatch.setattr(flow_init, "create_or_replace_item_progress_view", rebuild)
    scalar.convert_stored_instants(blank, (("projection_clock", "observed_at"),))
    assert restored == [True]
    assert (
        format_instant(
            blank.execute("SELECT observed_at FROM item_progress_view").fetchone()[0]
        )
        == STAMP
    )
    scalar.convert_stored_instants(blank, (("projection_clock", "observed_at"),))
    assert restored == [True]
    blank.rollback()
    assert blank.execute("SELECT to_regclass('projection_clock')").fetchone()[0] is None


@pytest.mark.parametrize("dependent", ["direct", "child", "custom"])
def test_unowned_or_custom_view_refuses_before_drop_or_ddl(blank, dependent):
    _view_fixture(
        blank, "unowned_clock_view" if dependent == "direct" else "item_progress_view"
    )
    if dependent == "child":
        blank.execute(
            "CREATE VIEW unowned_clock_view AS SELECT * FROM item_progress_view"
        )
    elif dependent == "custom":
        blank.execute("COMMENT ON VIEW item_progress_view IS 'owner metadata'")
    expected = (
        "instant_dependent_view_customized"
        if dependent == "custom"
        else "instant_dependent_view_unowned"
    )
    with pytest.raises(RuntimeError, match=expected):
        scalar.convert_stored_instants(blank, (("projection_clock", "observed_at"),))
    assert (
        blank.execute("SELECT observed_at FROM projection_clock")
        .fetchone()[0]
        .endswith("1234569Z")
    )
    name = "unowned_clock_view" if dependent == "direct" else "item_progress_view"
    assert blank.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is not None

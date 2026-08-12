"""Workflow-surface compatibility and content-count portability tests."""

from __future__ import annotations

from runtime.api.domain.test_universe_portability import (
    _canonical_test_universe,
)
from yoke_core.domain import universe_portability as portability


def test_additive_work_surfaces_accept_older_archive_shapes():
    additive_tables = {
        "addressed_event_deliveries",
        "decision_request_actor_authorities",
        "decision_request_role_authorities",
        "decision_requests",
        "item_strategy_docs",
        "qa_methods",
        "qa_plan_cases",
        "qa_plan_item_attachments",
        "qa_plan_project_defaults",
        "qa_plans",
        "strategy_doc_claims",
        "test_machine_verifications",
    }
    assert additive_tables <= portability._ARCHIVE_OMITTABLE_TARGET_TABLES
    assert additive_tables <= set(portability.USER_CONTENT_TABLES)
    assert "migration_content_adoptions" in portability._ARCHIVE_OMITTABLE_TARGET_TABLES
    assert portability._compatible_restore_columns(
        "applied_migrations",
        ("migration_name", "applied_at", "applied_by", "minimum_serving_version"),
        (
            "migration_name",
            "applied_at",
            "applied_by",
            "minimum_serving_version",
            "content_sha256",
        ),
    ) == (
        "migration_name",
        "applied_at",
        "applied_by",
        "minimum_serving_version",
    )
    legacy_delivery_columns = (
        "id",
        "channel",
        "event_id",
        "actor_id",
        "notification_kind",
        "reason",
        "read_at",
        "created_at",
    )
    assert (
        portability._compatible_restore_columns(
            "addressed_event_deliveries",
            legacy_delivery_columns,
            legacy_delivery_columns
            + (
                "event_name",
                "project_id",
                "event_outcome",
                "event_actor_id",
                "event_actor_label",
                "event_envelope",
            ),
        )
        == legacy_delivery_columns
    )
    assert portability._compatible_restore_columns(
        "qa_requirements",
        ("id", "created_at"),
        (
            "id",
            "plan_id",
            "plan_case_key",
            "case_position",
            "baseline_position",
            "method_id",
            "method_name",
            "runner_id",
            "required_capability_kind",
            "verdict_path",
            "host_baseline",
            "entry_surface",
            "required_completion",
            "workflow_transition_id",
            "instructions",
            "expected_outcome",
            "method_config",
            "created_at",
        ),
    ) == ("id", "created_at")
    assert portability._compatible_restore_columns(
        "qa_runs",
        ("id", "created_at"),
        ("id", "case_outcome", "capture_degraded_reason", "created_at"),
    ) == ("id", "created_at")
    assert portability._compatible_restore_columns(
        "strategy_docs",
        ("id", "slug"),
        ("id", "slug", "parent_slug"),
    ) == ("id", "slug")
    assert portability._compatible_restore_columns(
        "strategy_doc_revisions",
        ("id", "slug"),
        ("id", "slug", "session_id"),
    ) == ("id", "slug")


def test_user_content_counts_detects_nonempty_universe():
    with _canonical_test_universe() as (conn, _dsn):
        # The general API fixture carries two synthetic project rows; a newly
        # born product universe does not. Remove fixture-only content first.
        conn.execute("DELETE FROM api_token_audit")
        conn.execute("DELETE FROM api_tokens")
        conn.execute("DELETE FROM projects")
        conn.execute(
            "INSERT INTO migration_audit "
            "(migration_name, tables_declared, expected_deltas, pre_row_counts, "
            "backup_path, state, started_at) VALUES "
            "('maintenance-receipt', '[]', '{}', '{}', 'none', 'completed', now())"
        )
        conn.commit()
        empty_counts = portability.user_content_counts(conn)
        assert "migration_audit" not in empty_counts
        assert all(value == 0 for value in empty_counts.values())
        assert empty_counts["qa_methods"] == 0
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at)"
            " VALUES (98999, 'method-owner', 'Method Owner', 'MET', now())"
        )
        conn.execute(
            "INSERT INTO qa_methods ("
            "id, name, description, source_kind, project_id, runner_id, "
            "verdict_path, verdict_contract, evidence_contract, created_at, "
            "updated_at"
            ") VALUES ("
            "'project-method', 'Project method', 'Project-owned verifier', "
            "'project', 98999, 'project_runner', 'automatic', 'exit 0', "
            "'captured output', now(), now()"
            ")"
        )
        assert portability.user_content_counts(conn)["qa_methods"] == 1
        conn.execute("DELETE FROM qa_methods WHERE id = 'project-method'")
        conn.execute("DELETE FROM projects WHERE id = 98999")
        conn.commit()
        actor_id = conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[
            0
        ]
        conn.execute(
            "INSERT INTO api_tokens "
            "(id, token_hash, actor_id, name, status, created_at) "
            "VALUES (99000, 'credential-only', %s, 'extra', 'active', now())",
            (actor_id,),
        )
        conn.commit()
        assert portability.user_content_counts(conn)["api_tokens"] == 1
        conn.execute("DELETE FROM api_tokens WHERE id = 99000")
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at)"
            " VALUES (99001, 'not-empty', 'Not Empty', 'NON', now())"
        )
        assert portability.user_content_counts(conn)["projects"] == 1
        conn.execute("DELETE FROM projects WHERE id = 99001")
        conn.execute(
            "INSERT INTO ouroboros_entries"
            " (id, timestamp, agent, category, body, created_at, project_id)"
            " VALUES (99002, 'now', 'tester', 'observation', 'real work',"
            " 'now', NULL)"
        )
        conn.commit()
        assert portability.user_content_counts(conn)["ouroboros_entries"] == 1
        conn.execute(
            "INSERT INTO project_onboarding_runs "
            "(run_id, schema_version, branch, status, metadata_json, created_at, "
            "updated_at) VALUES "
            "('content-run', 1, 'local-checkout', 'open', '{}', 'now', 'now')"
        )
        conn.commit()
        counts = portability.user_content_counts(conn)
        assert counts["project_onboarding_runs"] == 1
        conn.execute("CREATE TABLE future_content (id integer primary key)")
        conn.execute("INSERT INTO future_content (id) VALUES (1)")
        conn.commit()
        assert portability.all_table_row_counts(conn)["future_content"] == 1

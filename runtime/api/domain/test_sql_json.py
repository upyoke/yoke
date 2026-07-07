"""Shape-only tests for yoke_core.domain.sql_json."""

from __future__ import annotations

from yoke_core.domain import sql_json
from yoke_core.domain.sql_json import (
    JSONB_COLUMNS,
    json_get,
    json_set_expr,
    json_valid_expr,
)


class TestJsonGet:
    def test_basic_extract_shape(self) -> None:
        assert (
            json_get("envelope", "$.context.detail.item")
            == "NULLIF(envelope, '')::jsonb #>> '{context,detail,item}'"
        )

    def test_simple_top_level_path(self) -> None:
        assert json_get("col", "$.x") == "NULLIF(col, '')::jsonb #>> '{x}'"

    def test_column_expr_can_be_qualified(self) -> None:
        """The column_expr argument is interpolated verbatim, so table-qualified
        expressions work."""
        assert (
            json_get("events.envelope", "$.session_id")
            == "NULLIF(events.envelope, '')::jsonb #>> '{session_id}'"
        )

    def test_returns_string(self) -> None:
        assert isinstance(json_get("envelope", "$.x"), str)


class TestJsonSetExpr:
    def test_placeholder_value(self) -> None:
        """A bound placeholder flows through unchanged."""
        assert json_set_expr("envelope", "$.context.project", "%s") == (
            "jsonb_set(COALESCE(NULLIF(envelope, '')::jsonb, '{}'::jsonb), "
            "'{context,project}', to_jsonb(%s))::text"
        )

    def test_sql_fragment_value(self) -> None:
        """value_sql is inlined verbatim so nested expressions are allowed."""
        assert json_set_expr("envelope", "$.updated_at", "CURRENT_TIMESTAMP") == (
            "jsonb_set(COALESCE(NULLIF(envelope, '')::jsonb, '{}'::jsonb), "
            "'{updated_at}', to_jsonb(CURRENT_TIMESTAMP))::text"
        )

    def test_returns_string(self) -> None:
        assert isinstance(json_set_expr("envelope", "$.x", "%s"), str)


class TestJsonValidExpr:
    def test_basic_predicate_shape(self) -> None:
        """Emits the native Postgres ``IS JSON`` predicate, not ``json_valid``."""
        assert json_valid_expr("stages") == "(stages IS JSON)"

    def test_column_expr_can_be_qualified(self) -> None:
        assert json_valid_expr("qr.raw_result") == "(qr.raw_result IS JSON)"

    def test_no_sqlite_json_valid_token(self) -> None:
        assert "json_valid" not in json_valid_expr("envelope")

    def test_returns_string(self) -> None:
        assert isinstance(json_valid_expr("envelope"), str)


class TestJsonbColumns:
    def test_is_mapping(self) -> None:
        """JSONB_COLUMNS is exported for cross-module reuse."""
        assert isinstance(JSONB_COLUMNS, dict) or hasattr(
            JSONB_COLUMNS, "__getitem__"
        )

    def test_has_events_envelope(self) -> None:
        assert "envelope" in JSONB_COLUMNS["events"]

    def test_has_items_browser_qa_metadata(self) -> None:
        assert "browser_qa_metadata" in JSONB_COLUMNS["items"]

    def test_has_items_db_mutation_profile(self) -> None:
        assert "db_mutation_profile" in JSONB_COLUMNS["items"]

    def test_has_items_db_compatibility_attestation(self) -> None:
        assert "db_compatibility_attestation" in JSONB_COLUMNS["items"]

    def test_has_qa_runs_raw_result(self) -> None:
        assert "raw_result" in JSONB_COLUMNS["qa_runs"]

    def test_has_qa_artifacts_metadata(self) -> None:
        assert "metadata" in JSONB_COLUMNS["qa_artifacts"]

    def test_has_deployment_flows_stages(self) -> None:
        assert "stages" in JSONB_COLUMNS["deployment_flows"]

    def test_events_anomaly_flags_listed(self) -> None:
        assert "anomaly_flags" in JSONB_COLUMNS["events"]

    def test_excludes_markdown_columns(self) -> None:
        """Structured-markdown fields on items are NOT JSONB candidates."""
        items_columns = set(JSONB_COLUMNS.get("items", ()))
        for md_col in (
            "spec",
            "design_spec",
            "technical_plan",
            "worktree_plan",
            "shepherd_log",
            "shepherd_caveats",
            "test_results",
            "deploy_log",
        ):
            assert md_col not in items_columns, (
                f"items.{md_col} is markdown; must not appear in JSONB_COLUMNS"
            )

    def test_excludes_epic_progress_notes_body(self) -> None:
        epn = JSONB_COLUMNS.get("epic_progress_notes", ())
        assert "body" not in epn


class TestModuleDunderAll:
    def test_all_is_complete(self) -> None:
        assert set(sql_json.__all__) >= {
            "JSONB_COLUMNS",
            "json_get",
            "json_set_expr",
            "json_valid_expr",
        }

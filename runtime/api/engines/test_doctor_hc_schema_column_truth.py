"""Curated teaching metadata cannot prove that a physical column is absent."""

from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES
from yoke_core.domain.schema_expected_catalog import parse_expected_schema
from yoke_project_checks import check_tier_schema_bleed as check


def test_packet_omission_keeps_real_merge_timestamp_as_structural_truth():
    assert "merged_at" not in dict(CANONICAL_TABLES["items"]["columns"])
    assert parse_expected_schema()["items"]["merged_at"] == "TIMESTAMPTZ"
    findings = check._scan_file("guide.md", "The item records items.merged_at.\n")
    assert len(findings) == 1
    assert "restates Tier 1 structural truth" in findings[0]
    assert "non-existent" not in findings[0]


def test_truly_missing_column_still_reports_confabulation():
    field = "nonexistent_landing_time"
    assert field not in parse_expected_schema()["items"]
    findings = check._scan_file("guide.md", f"The item records items.{field}.\n")
    assert len(findings) == 1
    assert "non-existent column" in findings[0]
    assert "confabulation" in findings[0]


def test_column_truth_does_not_expand_curated_table_scope():
    assert set(check._TABLE_COLUMNS) <= set(CANONICAL_TABLES)
    assert all(
        set(columns) == set(parse_expected_schema()[table])
        for table, columns in check._TABLE_COLUMNS.items()
    )

"""Unit tests for https doctor LOCAL+relay composition helpers."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters.doctor_https_compose import (
    false_na_local_runtime_slugs,
    false_na_source_slugs,
    merge_relayed_with_local,
    recount,
)


def test_false_na_local_runtime_slugs_selects_machine_checks() -> None:
    rows = [
        {
            "hc": "HC-session-relay",
            "severity": "N/A",
            "detail": "declared for the local runtime; this run is hosted",
        },
        {
            "hc": "HC-status-consistency",
            "severity": "N/A",
            "detail": "unrelated",
        },
        {
            "hc": "HC-local-operating-actor-authority",
            "severity": "N/A",
            "detail": "declared for the local runtime; this run is hosted",
        },
    ]

    assert false_na_local_runtime_slugs(rows) == ["session-relay"]


def test_false_na_source_slugs_filters_checkout_gaps() -> None:
    rows = [
        {
            "hc": "HC-file-line-limit",
            "severity": "N/A",
            "detail": "reads the 1 source tree; this runner has no checkout for it (hosted runtime)",
        },
        {
            "hc": "HC-status-consistency",
            "severity": "PASS",
            "detail": "",
        },
        {
            "hc": "HC-worktree-health",
            "severity": "N/A",
            "detail": "something else",
        },
        {
            # Older server builds still N/A snapshot HCs with the checkout
            # detail even after this client reclassified them as DB-only.
            "hc": "HC-architecture-unclassified-path",
            "severity": "N/A",
            "detail": "reads the 1 source tree; this runner has no checkout for it (hosted runtime)",
        },
    ]
    assert false_na_source_slugs(rows) == [
        "file-line-limit",
        "architecture-unclassified-path",
    ]


def test_merge_replaces_false_na_with_local_verdict() -> None:
    relayed = [
        {
            "hc": "HC-file-line-limit",
            "name": "Authored file 350-line limit",
            "severity": "N/A",
            "detail": "reads the yoke source tree; this runner has no checkout for it (hosted runtime)",
        },
        {
            "hc": "HC-status-consistency",
            "name": "Status consistency",
            "severity": "PASS",
            "detail": "",
        },
    ]
    local = [
        {
            "hc": "HC-file-line-limit",
            "name": "Authored file 350-line limit",
            "severity": "PASS",
            "detail": "",
        },
    ]
    merged = merge_relayed_with_local(relayed, local)
    by_hc = {row["hc"]: row for row in merged}
    assert by_hc["HC-file-line-limit"]["severity"] == "PASS"
    assert by_hc["HC-status-consistency"]["severity"] == "PASS"
    assert recount(merged)["pass_count"] == 2
    assert recount(merged)["na_count"] == 0


def test_composition_preserves_each_named_incomplete_and_internal_error():
    relayed = [
        {
            "hc": "HC-check-incomplete",
            "name": "Hosted audit",
            "severity": "FAIL",
            "detail": "deadline",
        }
    ]
    local = [
        {"hc": hc, "name": name, "severity": "FAIL", "detail": "deadline"}
        for hc in ("HC-check-incomplete", "HC-internal-error")
        for name in ("First source check", "Second source check")
    ]
    merged = merge_relayed_with_local(relayed, local)
    assert merged == relayed + local
    assert recount(merged)["fail_count"] == 5
    assert merge_relayed_with_local(merged, []) == merged


@pytest.mark.parametrize("scope", ["project", "source"])
@pytest.mark.parametrize("source_verdict", ["PASS", "FAIL"])
def test_missing_database_keeps_completed_source_verdict(
    scope, source_verdict, tmp_path, monkeypatch
):
    from yoke_core.engines import doctor_https_compose as source
    from yoke_core.engines import doctor_https_only as project
    from yoke_core.engines.doctor_project_checks import Discovery
    from yoke_core.engines.doctor_registry_types import HealthCheck

    marker = tmp_path / "source.py"
    marker.write_text("source evidence", encoding="utf-8")

    def mixed_check(conn, args, rec):
        assert marker.read_text(encoding="utf-8") == "source evidence"
        rec.record(
            "HC-mixed-source-backlog",
            "Mixed source/backlog",
            source_verdict,
            "completed source finding",
        )
        conn.execute("SELECT id FROM items")

    check = HealthCheck("mixed-source-backlog", "Mixed source/backlog", mixed_check)
    module = project if scope == "project" else source
    monkeypatch.setattr(module, "checkout_root_for_project", lambda _: tmp_path)
    monkeypatch.setattr(module, "local_connection_or_none", lambda _: None)
    if scope == "project":
        monkeypatch.setattr(
            project, "discover_project_checks", lambda _: Discovery([check], [])
        )
        rows = project.run_local_project_checks(project="example", slugs=[check.slug])
    else:
        monkeypatch.setattr(source, "HEALTH_CHECKS", [check])
        rows = source.run_local_source_checks(
            project="example",
            quick=False,
            full=False,
            fix=False,
            only=check.slug,
            slugs=[check.slug],
        )
    assert len(rows) == 2
    assert all(row["hc"] == "HC-mixed-source-backlog" for row in rows)
    assert all(row["name"] == "Mixed source/backlog" for row in rows)
    assert rows[0]["severity"] == source_verdict
    assert rows[0]["detail"] == "completed source finding"
    assert rows[1]["severity"] == "N/A"
    assert "no local-postgres authority" in rows[1]["detail"]
    relayed = [{"hc": "HC-mixed-source-backlog", "severity": "N/A"}]
    assert source.merge_relayed_with_local(relayed, rows) == rows
    assert source.merge_relayed_with_local([], rows) == rows


def test_unrelated_internal_error_remains_a_failure():
    from yoke_core.engines.doctor_https_compose import note_missing_control_plane
    from yoke_core.engines.doctor_registry_types import HealthCheck
    from yoke_core.engines.doctor_report import CheckResult

    record = CheckResult(
        "HC-internal-error", "Broken check", "FAIL", "ValueError: malformed evidence"
    )
    check = HealthCheck("broken-check", "Broken check", lambda *_: None)
    note_missing_control_plane([record], "example", check)
    assert record.check_id == "HC-internal-error"
    assert record.result == "FAIL"


def test_retired_source_finding_survives_unavailable_backlog(tmp_path, monkeypatch):
    from yoke_project_checks import check_obsoleted_terms as scan
    from yoke_core.engines import doctor_https_only as project
    from yoke_core.engines.doctor_project_checks import Discovery

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("retired token\n", encoding="utf-8")
    pattern = r"\bretired token\b"
    monkeypatch.setattr(scan, "OBSOLETED_TERM_PATTERNS", (pattern,))
    monkeypatch.setattr(scan, "OBSOLETED_TERM_LABELS", {pattern: "Retired token"})
    monkeypatch.setattr(scan, "_resolve_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(project, "checkout_root_for_project", lambda _: tmp_path)
    monkeypatch.setattr(project, "local_connection_or_none", lambda _: None)
    monkeypatch.setattr(
        project,
        "discover_project_checks",
        lambda _: Discovery(scan.PROJECT_HEALTH_CHECKS, []),
    )
    rows = project.run_local_project_checks(project="example", full=True, slugs=[])
    assert [row["severity"] for row in rows] == ["WARN", "N/A"]
    assert "docs/guide.md:1: [Retired token]" in rows[0]["detail"]
    assert "no local-postgres authority" in rows[1]["detail"]

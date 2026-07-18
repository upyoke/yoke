"""Tests for the Python doctor engine (DB-only health checks): part 1.

Status-consistency tests live in test_doctor_db_status_consistency.py.
Mid-section HCs live in test_doctor_db_hcs_a.py.
Late-section HCs live in test_doctor_db_hcs_b.py.
Exit-code tests live in test_doctor_db_exit.py.

Schema scaffolding shared via _doctor_db_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines.doctor import (
    DoctorArgs,
    HEALTH_CHECKS,
    RecordCollector,
    hc_backlog_hygiene,
    hc_blocked_items,
    hc_dispatch_chain,
    hc_frontmatter_schema,
    hc_title_length,
    parse_args,
    run_checks,
)

from yoke_core.engines._doctor_db_test_helpers import (
    _default_args,
    _get_result,
    _iso_offset,
    _p,
    conn,
)


class TestRecordCollector:
    def test_empty_collector(self):
        rec = RecordCollector()
        assert rec.pass_count == 0
        assert rec.warn_count == 0
        assert rec.fail_count == 0
        assert rec.total_count == 0

    def test_record_counts(self):
        rec = RecordCollector()
        rec.record("HC-a", "A", "PASS", "")
        rec.record("HC-b", "B", "WARN", "warning detail")
        rec.record("HC-c", "C", "FAIL", "failure detail")
        assert rec.pass_count == 1
        assert rec.warn_count == 1
        assert rec.fail_count == 1
        assert rec.total_count == 3

    def test_format_report_header(self):
        rec = RecordCollector()
        rec.record("HC-test", "Test Check", "PASS", "")
        report = rec.format_report()
        assert report.startswith("# Ouroboros Health Report")
        assert "## Summary" in report
        assert "1 checks run: 1 passed, 0 warnings, 0 failures" in report

    def test_format_report_sections(self):
        rec = RecordCollector()
        rec.record("HC-f", "Fail Check", "FAIL", "bad stuff")
        rec.record("HC-w", "Warn Check", "WARN", "concern")
        rec.record("HC-p", "Pass Check", "PASS", "")
        report = rec.format_report()
        # Sections appear in FAIL, WARN, PASS order
        fail_pos = report.index("## Failures")
        warn_pos = report.index("## Warnings")
        pass_pos = report.index("## Passed")
        assert fail_pos < warn_pos < pass_pos
        assert "### HC-f: Fail Check" in report
        assert "### HC-w: Warn Check" in report
        assert "HC-p: Pass Check" in report

    def test_pass_with_detail(self):
        rec = RecordCollector()
        rec.record("HC-p", "Pass", "PASS", "extra info")
        report = rec.format_report()
        assert "HC-p: Pass \u2014 extra info" in report


class TestFiltering:
    def test_only_filter(self):
        args = _default_args(only="status-consistency,blocked-items")
        from yoke_core.engines.doctor import _should_run_hc
        assert _should_run_hc("status-consistency", args) is True
        assert _should_run_hc("blocked-items", args) is True
        assert _should_run_hc("dispatch-chain", args) is False

    def test_legacy_hc_aliases_filter(self):
        args = _default_args(only="HC-confabulation")
        from yoke_core.engines.doctor import _should_run_hc
        assert _should_run_hc("path-confabulation", args) is True

    def test_quick_skips_gh(self):
        args = _default_args(quick=True)
        from yoke_core.engines.doctor import _should_run_hc
        assert _should_run_hc("orphaned-gh-issues", args) is False
        assert _should_run_hc("status-consistency", args) is True

    def test_no_filter_runs_all(self):
        args = _default_args()
        from yoke_core.engines.doctor import _should_run_hc
        assert _should_run_hc("status-consistency", args) is True
        assert _should_run_hc("dispatch-chain", args) is True


class TestParseArgs:
    def test_quick_scope(self):
        args = parse_args(["--quick"])
        assert args.file is None
        assert args.fix is False
        assert args.only is None
        assert args.quick is True
        assert args.project == "yoke"

    def test_full_scope(self):
        args = parse_args(["--full"])
        assert args.quick is False

    def test_requires_scope_flag(self):
        import pytest as _pytest
        with _pytest.raises(SystemExit):
            parse_args([])

    def test_all_flags(self):
        args = parse_args(["--file", "/tmp/r.md", "--fix", "--only", "a,b", "--quick", "--project", "externalwebapp"])
        assert args.file == "/tmp/r.md"
        assert args.fix is True
        assert args.only == "a,b"
        assert args.quick is True
        assert args.project == "externalwebapp"

    def test_legacy_check_aliases(self):
        args = parse_args(["--repo-root", ".", "--check", "HC-confabulation"])
        assert args.only == "HC-confabulation"

    def test_only_satisfies_scope_requirement(self):
        # --only is itself an explicit narrow scope; no need to also pass --quick/--full
        args = parse_args(["--only", "status-consistency"])
        assert args.only == "status-consistency"
        assert args.quick is False


class TestHCBlockedItems:
    def test_pass_no_blocked(self, conn):
        conn.execute("INSERT INTO items (id, title, type, status, priority) VALUES (1, 'T', 'issue', 'idea', 'low')")
        rec = RecordCollector()
        hc_blocked_items(conn, _default_args(), rec)
        assert _get_result(rec, "HC-blocked-items").result == "PASS"

    def test_warn_recently_blocked(self, conn):
        # HC-blocked-items now ages flag-driven blocks.
        p = _p(conn)
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, updated_at, blocked, blocked_reason) "
            f"VALUES (1, 'T', 'issue', 'implementing', 'low', {p}, 1, 'paused')",
            (_iso_offset(days=-3),),
        )
        rec = RecordCollector()
        hc_blocked_items(conn, _default_args(), rec)
        r = _get_result(rec, "HC-blocked-items")
        assert r.result == "WARN"

    def test_fail_long_blocked(self, conn):
        # HC-blocked-items now ages flag-driven blocks.
        p = _p(conn)
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, updated_at, blocked, blocked_reason) "
            f"VALUES (1, 'T', 'issue', 'implementing', 'low', {p}, 1, 'paused')",
            (_iso_offset(days=-45),),
        )
        rec = RecordCollector()
        hc_blocked_items(conn, _default_args(), rec)
        r = _get_result(rec, "HC-blocked-items")
        assert r.result == "FAIL"
        assert ">30" in r.detail


class TestHCDispatchChain:
    def test_pass_empty(self, conn):
        rec = RecordCollector()
        hc_dispatch_chain(conn, _default_args(), rec)
        assert _get_result(rec, "HC-dispatch-chain").result == "PASS"

    def test_fail_epic_no_tasks(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (5, 'E', 'epic', 'implementing', 'high')"
        )
        rec = RecordCollector()
        hc_dispatch_chain(conn, _default_args(), rec)
        r = _get_result(rec, "HC-dispatch-chain")
        assert r.result == "FAIL"
        assert "no tasks in DB" in r.detail

    def test_pass_refined_idea_epic_without_tasks(self, conn):
        # refined-idea epics legitimately have no epic_tasks rows; shepherd
        # populates them on the refined-idea -> planning transition.
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (6, 'E', 'epic', 'refined-idea', 'high')"
        )
        rec = RecordCollector()
        hc_dispatch_chain(conn, _default_args(), rec)
        r = _get_result(rec, "HC-dispatch-chain")
        assert r.result == "PASS"


class TestHCBacklogHygiene:
    def test_pass_complete(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'Good', 'issue', 'idea', 'low')"
        )
        rec = RecordCollector()
        hc_backlog_hygiene(conn, _default_args(), rec)
        assert _get_result(rec, "HC-backlog-hygiene").result == "PASS"

    def test_warn_missing_priority(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (1, 'NoPri', 'issue', 'idea')"
        )
        rec = RecordCollector()
        hc_backlog_hygiene(conn, _default_args(), rec)
        r = _get_result(rec, "HC-backlog-hygiene")
        assert r.result == "WARN"
        assert "missing priority" in r.detail


class TestHCFrontmatterSchema:
    def test_pass_valid(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, github_issue, flow) "
            "VALUES (1, 'OK', 'issue', 'idea', 'low', '#42', 'full')"
        )
        rec = RecordCollector()
        hc_frontmatter_schema(conn, _default_args(), rec)
        assert _get_result(rec, "HC-frontmatter-schema").result == "PASS"

    def test_warn_invalid_type(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'Bad', 'task', 'idea', 'low')"
        )
        rec = RecordCollector()
        hc_frontmatter_schema(conn, _default_args(), rec)
        r = _get_result(rec, "HC-frontmatter-schema")
        assert r.result == "WARN"
        assert "invalid type" in r.detail

    def test_warn_bad_github_issue(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, github_issue) "
            "VALUES (1, 'Bad', 'issue', 'idea', 'low', 'abc')"
        )
        rec = RecordCollector()
        hc_frontmatter_schema(conn, _default_args(), rec)
        r = _get_result(rec, "HC-frontmatter-schema")
        assert r.result == "WARN"
        assert "does not match #N format" in r.detail

    def test_pass_accelerated_frontmatter_flow(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, github_issue, flow) "
            "VALUES (1, 'OK', 'issue', 'idea', 'low', '#42', 'accelerated')"
        )
        rec = RecordCollector()
        hc_frontmatter_schema(conn, _default_args(), rec)
        r = _get_result(rec, "HC-frontmatter-schema")
        assert r.result == "PASS"

    def test_warn_unregistered_flow(self, conn):
        # Deployment pipeline ids belong in deployment_flow, not the legacy
        # frontmatter flow/speed column.
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, flow) "
            "VALUES (1, 'Bad', 'issue', 'idea', 'low', 'yoke-internal')"
        )
        rec = RecordCollector()
        hc_frontmatter_schema(conn, _default_args(), rec)
        r = _get_result(rec, "HC-frontmatter-schema")
        assert r.result == "WARN"
        assert "invalid flow 'yoke-internal'" in r.detail


class TestHCTitleLength:
    def test_pass_short_title(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'Short', 'issue', 'idea', 'low')"
        )
        rec = RecordCollector()
        hc_title_length(conn, _default_args(), rec)
        assert _get_result(rec, "HC-title-length").result == "PASS"

    def test_warn_long_title(self, conn):
        long_title = "A" * 120
        p = _p(conn)
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            f"VALUES (1, {p}, 'issue', 'idea', 'low')",
            (long_title,),
        )
        rec = RecordCollector()
        hc_title_length(conn, _default_args(), rec)
        r = _get_result(rec, "HC-title-length")
        assert r.result == "WARN"
        assert "120 chars" in r.detail

    def test_warn_long_task_title(self, conn):
        long_title = "B" * 105
        p = _p(conn)
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status) "
            f"VALUES (1, 1, {p}, 'planning')",
            (long_title,),
        )
        rec = RecordCollector()
        hc_title_length(conn, _default_args(), rec)
        r = _get_result(rec, "HC-title-length")
        assert r.result == "WARN"
        assert "105 chars" in r.detail

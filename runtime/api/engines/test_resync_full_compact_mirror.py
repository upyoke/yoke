"""AC-4 stage-2 compare tests: compact-mirror suppression in the body detector.

Split from ``test_resync_full_compare_text.py`` so each authored test
file stays under the 350-line limit. Other stage-2 tests (title, body,
label, state, frozen, comment) live in their sibling modules.

Pytest fixtures (``test_db``) are shared via the private
``_resync_full_test_helpers`` module.
"""

from __future__ import annotations

from yoke_core.engines.resync import PairedItem, stage2_compare
from yoke_core.domain import db_backend
from yoke_core.engines.resync_detect_compact_mirror import (
    COMPACT_MIRROR_FOOTER,
    _strip_evidence_section,
    matches_compact_mirror as _matches_compact_mirror,
)
from yoke_core.domain.backlog_github_body_budget import (
    GITHUB_BODY_BUDGET_BYTES,
    render_compact_mirror,
)
from runtime.api.fixtures.file_test_db import connect_test_db

from yoke_core.engines._resync_full_test_helpers import (
    _make_gh_issues,
    test_db,  # noqa: F401 — pytest fixture
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_oversize_item(db_path: str, *, item_id: int, spec_size: int) -> None:
    """Seed an item whose rendered body exceeds the GitHub body budget."""
    conn = connect_test_db(db_path)
    spec_text = "x" * spec_size
    p = _p(conn)
    conn.execute(
        "INSERT INTO items (id, title, status, priority, type, source, spec, "
        "frozen, github_issue, project_id, project_sequence) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, 0, {p}, 1, {p})",
        (
            item_id, "Oversize body item", "implementing", "high",
            "issue", "manual", spec_text, "#900", item_id,
        ),
    )
    conn.commit()
    conn.close()


class TestCompactMirrorSuppression:
    """Pre-AC-4, the detector compared the local body byte-for-byte against
    the GitHub body. When the write path published a compact mirror for an
    oversized body, every detect run flagged a false-positive body drift,
    ``--fix`` re-pushed the same compact mirror, and the next run flagged
    the same drift forever. AC-4 teaches the detector the compact-mirror
    contract: when the local body is over budget and GitHub carries the
    deterministic footer, recompute the expected compact mirror and
    suppress drift only when it matches (tolerating the ``## Evidence``
    event line)."""

    def test_strip_evidence_section_removes_evidence_content(self):
        body = (
            "## Identity\n- foo\n\n## Evidence\n- latest event: SectionUpserted "
            "at 2026-05-06T01:06:51Z\n\n_footer_\n"
        )
        stripped = _strip_evidence_section(body)
        assert "## Evidence" in stripped
        assert "SectionUpserted" not in stripped
        assert "_footer_" in stripped

    def test_matches_compact_mirror_returns_false_without_footer(self):
        """No compact-mirror footer means GitHub did not publish the mirror."""
        local = "x" * (GITHUB_BODY_BUDGET_BYTES + 200)
        assert not _matches_compact_mirror(
            local_body=local, gh_body="just some random body",
            item_fields={"title": "t", "status": "implementing", "type": "issue", "project": "yoke"},
            item_id=901,
        )

    def test_matches_compact_mirror_returns_false_when_under_budget(self):
        """Under-budget local body must NEVER match a mirror; the legitimate
        'shrink back to full' path emits real drift."""
        local = "small body"
        gh = render_compact_mirror(
            {"title": "t", "status": "implementing", "type": "issue", "project": "yoke"},
            conn=None, item_id=901,
        )
        assert COMPACT_MIRROR_FOOTER in gh
        assert not _matches_compact_mirror(
            local_body=local, gh_body=gh,
            item_fields={"title": "t", "status": "implementing", "type": "issue", "project": "yoke"},
            item_id=901,
        )

    def test_matches_compact_mirror_returns_true_when_matched(self):
        local = "x" * (GITHUB_BODY_BUDGET_BYTES + 200)
        fields = {"title": "Big", "status": "implementing", "type": "issue", "project": "yoke"}
        gh = render_compact_mirror(fields, conn=None, item_id=902)
        assert _matches_compact_mirror(
            local_body=local, gh_body=gh, item_fields=fields, item_id=902,
        )

    def test_stage2_suppresses_drift_when_mirror_matches(self, test_db):
        """End-to-end via stage2_compare: oversize local + compact-mirror GH ⇒ no drift."""
        _seed_oversize_item(test_db, item_id=910, spec_size=GITHUB_BODY_BUDGET_BYTES + 1000)
        fields = {
            "title": "Oversize body item",
            "status": "implementing",
            "type": "issue",
            "project": "yoke",
        }
        gh_body = render_compact_mirror(fields, conn=None, item_id=910)
        gh_issues = _make_gh_issues([{
            "number": 900,
            "title": "[YOK-910] Oversize body item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
            ],
            "state": "OPEN",
            "body": gh_body,
        }])
        paired = [PairedItem("YOK-910", "/tmp/910.md", 900, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, test_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert body_drifts == [], (
            "compact-mirror match must suppress body drift"
        )

    def test_stage2_reports_real_drift_when_local_under_budget_but_gh_has_mirror(
        self, test_db,
    ):
        """Legitimate 'shrink back to full' case — real drift, --fix resolves it."""
        conn = connect_test_db(test_db)
        p = _p(conn)
        conn.execute(
            "INSERT INTO items (id, title, status, priority, type, source, "
            "spec, frozen, github_issue, project_id, project_sequence) "
            f"VALUES ({p}, 'Small item', 'implementing', 'high', 'issue', 'manual', "
            f"'small spec', 0, '#901', 1, {p})",
            (911, 911),
        )
        conn.commit()
        conn.close()

        fields = {
            "title": "Small item", "status": "implementing", "type": "issue", "project": "yoke",
        }
        gh_body = render_compact_mirror(fields, conn=None, item_id=911)
        gh_issues = _make_gh_issues([{
            "number": 901,
            "title": "[YOK-911] Small item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
            ],
            "state": "OPEN",
            "body": gh_body,
        }])
        paired = [PairedItem("YOK-911", "/tmp/911.md", 901, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, test_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1, (
            "under-budget local + stale GH mirror MUST emit real drift"
        )

    def test_stage2_reports_real_drift_when_mirror_is_stale(self, test_db):
        """Over-budget local + stale compact mirror on GH (wrong title) → drift."""
        _seed_oversize_item(test_db, item_id=912, spec_size=GITHUB_BODY_BUDGET_BYTES + 1000)
        stale_fields = {
            "title": "WRONG TITLE",
            "status": "implementing",
            "type": "issue",
            "project": "yoke",
        }
        gh_body = render_compact_mirror(stale_fields, conn=None, item_id=912)
        gh_issues = _make_gh_issues([{
            "number": 902,
            "title": "[YOK-912] Oversize body item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
            ],
            "state": "OPEN",
            "body": gh_body,
        }])
        paired = [PairedItem("YOK-912", "/tmp/912.md", 902, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, test_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1, (
            "stale compact mirror MUST emit real body drift"
        )

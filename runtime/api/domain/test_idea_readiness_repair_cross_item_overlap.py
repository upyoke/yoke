"""Tests for yoke_core.domain.idea_readiness_repair_cross_item_overlap.

AC traceability:
- AC-1 / AC-3 / AC-5: ``probe_cross_item_overlap`` surfaces one issue
  per INCOMPATIBLE cluster; same-item, no-overlap, terminal-other-state,
  coordination_only, and directional activation cases all silence the
  cluster.
- AC-9: register-style semantics — planned sibling surfaces even
  though ``classify_overlap(phase='activate')`` would ignore it.
- AC-10: issue context carries every field needed to author the edge
  without a second schema hunt.
- AC-11: default repair path is evidence-returning and non-mutating.
- AC-12: ``auto_attest=True`` is rejected in v0.
- AC-13: no retired-snapshot surface references in implementation or
  test files.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

from yoke_core.domain.idea_readiness_repair_cross_item_overlap import (
    ISSUE_CODE,
    attempt_cross_item_overlap_repair,
    probe_cross_item_overlap,
)
import yoke_core.domain.idea_readiness_repair_cross_item_overlap as overlap_mod
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


_CANDIDATE_ITEM = 7001
_OTHER_ITEM = 7002


def _seed_item(conn, *, item_id: int, project: str = "yoke") -> int:
    project_id = 1 if project == "yoke" else int(project)
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'refining-idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    conn.commit()
    return item_id


def _ensure_item_dependencies_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS item_dependencies ("
        "id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL, "
        "blocking_item TEXT NOT NULL, "
        "gate_point TEXT NOT NULL DEFAULT 'activation', "
        "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
        "source TEXT NOT NULL, session_id INTEGER, "
        "rationale TEXT NOT NULL DEFAULT '', "
        "evidence_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL)"
    )
    conn.commit()


def _add_dep_edge(
    conn, *, dependent: int, blocking: int, gate_point: str = "activation",
):
    _ensure_item_dependencies_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, source, created_at) "
        "VALUES (%s, %s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}", gate_point),
    )
    conn.commit()


def _seed_claim(
    conn, *, item_id: int, target_id: int, state: str = "planned",
) -> int:
    actor = local_human(conn)
    activated = SNAP if state == "active" else None
    activated_at = "2026-05-01T01:00:00Z" if state == "active" else None
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, registered_at, "
        "activated_at, base_commit_sha) "
        "VALUES (%s, 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', %s, %s) RETURNING id",
        (state, actor, item_id, activated_at, activated),
    )
    cid = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


def _seed_two_items_sharing(conn, *, path_string: str):
    """Seed candidate + other item, both holding planned claims on a shared target."""
    target = seed_target(conn, path_string=path_string)
    cand = _seed_item(conn, item_id=_CANDIDATE_ITEM)
    other = _seed_item(conn, item_id=_OTHER_ITEM)
    cand_claim = _seed_claim(conn, item_id=cand, target_id=target, state="planned")
    other_claim = _seed_claim(conn, item_id=other, target_id=target, state="planned")
    return target, cand_claim, other_claim


class TestProbe:
    def test_incompatible_with_planned_sibling_surfaces(self, conn):
        target, cand_claim, other_claim = _seed_two_items_sharing(
            conn, path_string="runtime/api/domain/lint_shell_quoted_function_payload.py",
        )
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.code == ISSUE_CODE
        assert issue.context["candidate_item_id"] == _CANDIDATE_ITEM
        assert issue.context["candidate_claim_id"] == cand_claim
        assert issue.context["conflicting_claim_id"] == other_claim
        assert issue.context["conflicting_item_id"] == _OTHER_ITEM
        assert issue.context["integration_target"] == "main"
        assert issue.context["shared_paths"] == [
            "runtime/api/domain/lint_shell_quoted_function_payload.py",
        ]

    def test_same_item_idempotent_no_self_conflict(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        item = _seed_item(conn, item_id=_CANDIDATE_ITEM)
        # Two non-terminal claims on the SAME item — must NOT surface.
        _seed_claim(conn, item_id=item, target_id=target, state="planned")
        _seed_claim(conn, item_id=item, target_id=target, state="planned")
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert issues == []

    def test_no_overlap_pass(self, conn):
        target_a = seed_target(conn, path_string="runtime/api/domain")
        target_b = seed_target(conn, path_string="runtime/harness")
        cand = _seed_item(conn, item_id=_CANDIDATE_ITEM)
        other = _seed_item(conn, item_id=_OTHER_ITEM)
        _seed_claim(conn, item_id=cand, target_id=target_a, state="planned")
        _seed_claim(conn, item_id=other, target_id=target_b, state="planned")
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert issues == []

    def test_coordination_only_edge_silences_cluster(self, conn):
        _seed_two_items_sharing(conn, path_string="runtime/api/domain")
        _add_dep_edge(
            conn, dependent=_CANDIDATE_ITEM, blocking=_OTHER_ITEM,
            gate_point="coordination_only",
        )
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert issues == []

    def test_directional_activation_edge_silences_cluster(self, conn):
        _seed_two_items_sharing(conn, path_string="runtime/api/domain")
        # Candidate is DEPENDENT of a non-coordination edge — HAS_SERIAL.
        _add_dep_edge(
            conn, dependent=_CANDIDATE_ITEM, blocking=_OTHER_ITEM,
            gate_point="activation",
        )
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert issues == []

    def test_reverse_blocker_edge_silences_cluster(self, conn):
        # Candidate is the BLOCKER of a non-coordination edge: the
        # candidate is upstream and does not wait.
        _seed_two_items_sharing(conn, path_string="runtime/api/domain")
        _add_dep_edge(
            conn, dependent=_OTHER_ITEM, blocking=_CANDIDATE_ITEM,
            gate_point="activation",
        )
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert issues == []

    def test_terminal_other_state_ignored(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        cand = _seed_item(conn, item_id=_CANDIDATE_ITEM)
        other = _seed_item(conn, item_id=_OTHER_ITEM)
        _seed_claim(conn, item_id=cand, target_id=target, state="planned")
        # Other claim is released → terminal → must not surface.
        conn.execute(
            "INSERT INTO path_claims "
            "(state, mode, actor_id, item_id, integration_target, "
            "registered_at, released_at) "
            "VALUES ('released', 'exclusive', %s, %s, 'main', "
            "'2026-05-01T00:00:00Z', '2026-05-01T02:00:00Z')",
            (local_human(conn), other),
        )
        terminal_id = conn.execute(
            "SELECT id FROM path_claims WHERE state='released'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (int(terminal_id), target),
        )
        conn.commit()
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert issues == []

    def test_register_style_semantics_planned_siblings_surface(self, conn):
        """AC-9: planned sibling counts even though activate would ignore."""
        # Both planned — never activated. classify_overlap(phase='activate')
        # would return NONE; the probe MUST still surface this.
        target, cand_claim, other_claim = _seed_two_items_sharing(
            conn, path_string="runtime/api/domain",
        )
        # Sanity: both claims are planned, neither active.
        states = sorted(
            r[0] for r in conn.execute(
                "SELECT state FROM path_claims WHERE id IN (%s, %s)",
                (cand_claim, other_claim),
            )
        )
        assert states == ["planned", "planned"]
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert len(issues) == 1
        assert issues[0].context["classifier_phase"] == "register"

    def test_no_github_authh_claims_table_returns_empty(self, conn):
        # If the schema is incomplete, the probe must self-skip cleanly.
        conn.execute("DROP TABLE IF EXISTS path_claim_targets CASCADE")
        conn.execute("DROP TABLE IF EXISTS path_claims CASCADE")
        conn.commit()
        assert probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM) == []


class TestIssueContext:
    """AC-10: each issue carries every field needed to author the edge."""

    def test_context_completeness(self, conn):
        path = "runtime/api/domain/idea_readiness_check.py"
        target, cand_claim, other_claim = _seed_two_items_sharing(
            conn, path_string=path,
        )
        issues = probe_cross_item_overlap(conn, item_id=_CANDIDATE_ITEM)
        assert len(issues) == 1
        ctx = issues[0].context
        for key in (
            "candidate_item_id", "candidate_claim_id",
            "conflicting_claim_id", "conflicting_item_id",
            "integration_target", "shared_paths",
            "classifier_phase", "recovery_command",
        ):
            assert key in ctx, f"missing context key {key!r}"
        assert ctx["shared_paths"] == [path]
        assert (
            "yoke claims path coordination-decision-build"
            in ctx["recovery_command"]
        )
        assert f"YOK-{_CANDIDATE_ITEM}" in ctx["recovery_command"]
        assert str(other_claim) in ctx["recovery_command"]


class TestRepair:
    """AC-11 / AC-12: default repair is non-mutating; auto_attest rejected."""

    def test_repair_returns_evidence_packet(self, conn):
        _seed_two_items_sharing(conn, path_string="runtime/api/domain")
        # build_coordination_context reads spec via its own DB connection;
        # the in-memory fixture lacks the structured-field columns, so
        # mock the spec accessor it depends on.
        specs = {_CANDIDATE_ITEM: "# Candidate spec body",
                 _OTHER_ITEM: "# Other spec body"}

        def _fake_query_item(item_id, field):
            if field == "id":
                return str(item_id) if item_id in specs else ""
            return specs.get(item_id, "") if field == "spec" else ""

        # Pre-seed item_dependencies so the post-call no-write check has a
        # table to read; the helper must not insert into it.
        _ensure_item_dependencies_table(conn)
        with mock.patch(
            "yoke_core.domain.path_claim_coordination_decision."
            "query_item",
            side_effect=_fake_query_item,
        ):
            outcome = attempt_cross_item_overlap_repair(
                conn, item_id=_CANDIDATE_ITEM,
            )
        assert outcome.success is False
        assert outcome.auto_attest is False
        assert len(outcome.clusters) == 1
        cluster = outcome.clusters[0]
        assert cluster["conflicting_item_id"] == _OTHER_ITEM
        assert "coordination_context" in cluster
        ctx = cluster["coordination_context"]
        assert ctx["candidate_item_id"] == _CANDIDATE_ITEM
        rows = conn.execute(
            "SELECT COUNT(*) FROM item_dependencies "
            "WHERE dependent_item=%s OR blocking_item=%s",
            (f"YOK-{_CANDIDATE_ITEM}", f"YOK-{_CANDIDATE_ITEM}"),
        ).fetchone()
        assert rows[0] == 0

    def test_repair_no_clusters_returns_success(self, conn):
        # Seed candidate alone with a planned claim and no other items.
        target = seed_target(conn, path_string="runtime/api/domain")
        item = _seed_item(conn, item_id=_CANDIDATE_ITEM)
        _seed_claim(conn, item_id=item, target_id=target, state="planned")
        outcome = attempt_cross_item_overlap_repair(
            conn, item_id=_CANDIDATE_ITEM,
        )
        assert outcome.success is True
        assert outcome.clusters == []

    def test_auto_attest_true_rejected(self, conn):
        outcome = attempt_cross_item_overlap_repair(
            conn, item_id=_CANDIDATE_ITEM, auto_attest=True,
        )
        assert outcome.success is False
        assert outcome.auto_attest is True
        assert "reserved" in outcome.error


class TestRetiredSurfaceResidueAC13:
    """AC-13: implementation does not reference retired snapshot surfaces."""

    def test_no_retired_snapshot_references(self):
        # Scope per spec wording: "implementation-owned hits." This test
        # file declares the banned terms in its own regex, so itself is
        # excluded by design.
        impl = (
            Path(overlap_mod.__file__)
        )
        banned = re.compile(r"base_snapshot_id|_mint_target|path_snapshots")
        hits = [
            f"{impl}:{lineno}: {line}"
            for lineno, line in enumerate(
                impl.read_text(encoding="utf-8").splitlines(), start=1,
            )
            if banned.search(line)
        ]
        assert not hits, (
            "banned retired-surface reference found:\n" + "\n".join(hits)
        )

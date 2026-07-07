"""Tests for the no-claim exception mode and the claim-required gate.

Covers AC-1, AC-3, AC-4, AC-15, AC-22, AC-24 from the spec.
"""

from __future__ import annotations


import pytest

from yoke_core.domain._path_claims_test_helpers import (
    conn,  # noqa: F401
    local_human,
    seed_target,
)
from yoke_core.domain.path_claim_required_gate import (
    GATE_BLOCK,
    GATE_PASS,
    evaluate,
    is_satisfied,
    items_missing_coverage,
)
from yoke_core.domain.path_claims import (
    InvalidTargetSet,
    register,
)
from yoke_core.domain.path_claims_register import register_for_item
from yoke_core.domain.path_claims_exception import register_exception
from yoke_core.domain.path_integrity_invariants_claim_coverage import (
    check_path_claim_coverage,
)


def _seed_item(
    conn,
    *,
    item_id: int,
    status: str = "implementing",
    item_type: str = "issue",
    project: str = "yoke",
) -> None:
    row = conn.execute(
        "SELECT id FROM projects WHERE slug=%s",
        (project,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM projects",
        ).fetchone()
        project_id = int(row[0])
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, default_branch, public_item_prefix, "
            "created_at) VALUES "
            "(%s, %s, %s, 'main', 'TST', '2026-05-01T00:00:00Z')",
            (project_id, project, project),
        )
    else:
        project_id = int(row[0])
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, project_sequence, status, type, title, created_at, "
        "updated_at, source) "
        "VALUES (%s, %s, %s, %s, %s, 'test', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', '1') "
        "ON CONFLICT(id) DO NOTHING",
        (item_id, project_id, item_id, status, item_type),
    )


class TestExceptionRegister:
    def test_exception_lands_in_active_with_reason(self, conn):
        actor = local_human(conn)
        cid = register_exception(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[],
            exception_reason="validation-only ticket",
            item_id=42,
        )
        row = conn.execute(
            "SELECT mode, state, exception_reason FROM path_claims "
            "WHERE id = %s", (cid,),
        ).fetchone()
        assert row["mode"] == "exception"
        assert row["state"] == "active"
        assert row["exception_reason"] == "validation-only ticket"

    def test_exception_rejects_non_empty_target_set(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="x.py")
        with pytest.raises(InvalidTargetSet):
            register_exception(
                conn, actor_id=actor, integration_target="main",
                target_ids=[target], exception_reason="x",
            )

    def test_exception_rejects_empty_reason(self, conn):
        actor = local_human(conn)
        with pytest.raises(InvalidTargetSet):
            register_exception(
                conn, actor_id=actor, integration_target="main",
                target_ids=[], exception_reason="   ",
            )

    def test_register_dispatches_to_exception_helper(self, conn):
        actor = local_human(conn)
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[], mode="exception",
            exception_reason="meta-only ticket", item_id=99,
        )
        row = conn.execute(
            "SELECT mode, exception_reason FROM path_claims WHERE id = %s",
            (cid,),
        ).fetchone()
        assert row["mode"] == "exception"
        assert row["exception_reason"] == "meta-only ticket"

    def test_item_onramp_rejects_exception_with_paths(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=98)
        with pytest.raises(InvalidTargetSet):
            register_for_item(
                conn,
                item_id=98,
                integration_target="main",
                paths=["unexpected.py"],
                mode="exception",
                exception_reason="meta-only ticket",
                actor_id=actor,
            )


class TestClaimRequiredGate:
    def test_pass_with_exclusive_claim(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="a.py")
        _seed_item(conn, item_id=100)
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=100,
        )
        result = evaluate(conn, 100)
        assert result["verdict"] == GATE_PASS

    def test_pass_with_exception_claim(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=101)
        register_exception(
            conn, actor_id=actor, integration_target="main",
            target_ids=[], exception_reason="meta-only", item_id=101,
        )
        result = evaluate(conn, 101)
        assert result["verdict"] == GATE_PASS

    def test_block_when_no_claim(self, conn):
        _seed_item(conn, item_id=200)
        result = evaluate(conn, 200)
        assert result["verdict"] == GATE_BLOCK
        assert "no non-terminal path claim" in result["reason"]

    def test_block_when_only_terminal_claims(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="b.py")
        _seed_item(conn, item_id=201)
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=201,
        )
        conn.execute(
            "UPDATE path_claims SET state='released' WHERE id=%s", (cid,),
        )
        conn.commit()
        assert is_satisfied(conn, 201) is False

    def test_block_when_exclusive_claim_has_no_targets(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=202)
        conn.execute(
            "INSERT INTO path_claims "
            "(state, mode, actor_id, item_id, integration_target, "
            " registered_at) "
            "VALUES ('active', 'exclusive', %s, 202, 'main', "
            "'2026-05-01T00:00:00Z')",
            (actor,),
        )
        conn.commit()
        assert evaluate(conn, 202)["verdict"] == GATE_BLOCK

    def test_items_missing_coverage_filters_subset(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="c.py")
        for item_id in (300, 301, 302):
            _seed_item(conn, item_id=item_id)
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=300,
        )
        missing = items_missing_coverage(conn, [300, 301, 302])
        assert missing == [301, 302]


class TestCatchUpAudit:
    def test_invariant_finds_uncovered_non_terminal_items(self, conn):
        for item_id, status in (
            (400, "refined-idea"),
            (401, "implementing"),
            (402, "done"),  # terminal — ignored
        ):
            _seed_item(conn, item_id=item_id, status=status)
        actor = local_human(conn)
        target = seed_target(conn, path_string="covered.py")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=400,
        )
        failures = check_path_claim_coverage(conn, "yoke")
        failure_ids = {f[0] for f in failures}
        assert 400 not in failure_ids, "covered item should not fail"
        assert 402 not in failure_ids, "done item should not fail"
        assert 401 in failure_ids, "uncovered implementing item must fail"

    def test_invariant_treats_active_exception_as_satisfied(self, conn):
        _seed_item(conn, item_id=410)
        actor = local_human(conn)
        register_exception(
            conn, actor_id=actor, integration_target="main",
            target_ids=[], exception_reason="meta", item_id=410,
        )
        failures = check_path_claim_coverage(conn, "yoke")
        assert 410 not in {f[0] for f in failures}

    def test_invariant_rejects_exclusive_claim_with_zero_targets(self, conn):
        _seed_item(conn, item_id=411)
        actor = local_human(conn)
        conn.execute(
            "INSERT INTO path_claims "
            "(state, mode, actor_id, item_id, integration_target, "
            " registered_at) "
            "VALUES ('active', 'exclusive', %s, 411, 'main', "
            "'2026-05-01T00:00:00Z')",
            (actor,),
        )
        conn.commit()
        failures = check_path_claim_coverage(conn, "yoke")
        assert 411 in {f[0] for f in failures}

    def test_invariant_skips_other_projects(self, conn):
        _seed_item(conn, item_id=500, project="other-project")
        failures = check_path_claim_coverage(conn, "yoke")
        assert 500 not in {f[0] for f in failures}

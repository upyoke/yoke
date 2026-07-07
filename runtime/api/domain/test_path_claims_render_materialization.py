"""Render coverage for materialization_state and exception claims.

Covers AC-12 (render exposes materialization_state), AC-22 (no-claim
exception renders as a dedicated block carrying the operator's reason
verbatim) and AC (tentative coverage labels distinctly
in the rendered Path Claims section).
"""

from __future__ import annotations


from yoke_core.domain._path_claims_test_helpers import (
    conn,  # noqa: F401
    local_human,
)
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_exception import register_exception
from yoke_core.domain.path_claims_render import (
    _render_claim,
    render_path_claims_section,
)
from yoke_core.domain.path_registry import KIND_FILE
from yoke_core.domain.path_targets_planning import (
    plan_path_target,
    plan_tentative_path_target,
)


class TestRender:
    def test_planned_target_renders_with_state_tag(self, conn):
        actor = local_human(conn)
        future = plan_path_target(
            conn, project_id=1,
            path_string="future.py", kind=KIND_FILE, item_id=42,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[future], item_id=42,
        )
        rendered = render_path_claims_section(conn, 42)
        assert "(planned)" in rendered
        assert "future.py" in rendered

    def test_observed_target_renders_without_state_tag(self, conn):
        actor = local_human(conn)
        cur = conn.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, created_at, "
            " materialization_state, materialization_updated_at) "
            "VALUES (1, 'file', 'observed.py', 1, "
            "'2026-05-01T00:00:00Z', 'observed', '2026-05-01T00:00:00Z') "
            "RETURNING id"
        )
        observed_id = cur.fetchone()[0]
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[observed_id], item_id=43,
        )
        rendered = render_path_claims_section(conn, 43)
        assert "observed.py" in rendered
        assert "(planned)" not in rendered
        assert "(abandoned)" not in rendered

    def test_exception_claim_renders_dedicated_block_with_reason(self, conn):
        actor = local_human(conn)
        register_exception(
            conn, actor_id=actor, integration_target="main",
            target_ids=[], exception_reason="validation-only ticket",
            item_id=44,
        )
        rendered = render_path_claims_section(conn, 44)
        assert "**No-Claim Exception**" in rendered
        assert "validation-only ticket" in rendered
        assert "Declared coverage" not in rendered

    def test_mixed_claims_render_both_blocks(self, conn):
        actor = local_human(conn)
        future = plan_path_target(
            conn, project_id=1,
            path_string="leaf.py", kind=KIND_FILE, item_id=45,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[future], item_id=45,
        )
        register_exception(
            conn, actor_id=actor, integration_target="main",
            target_ids=[], exception_reason="follow-up exception",
            item_id=45,
        )
        rendered = render_path_claims_section(conn, 45)
        assert "(planned)" in rendered
        assert "**No-Claim Exception**" in rendered
        assert "follow-up exception" in rendered

    def test_tentative_target_renders_with_state_tag(self, conn):
        actor = local_human(conn)
        tentative = plan_tentative_path_target(
            conn, project_id=1,
            path_string="maybe.py", kind=KIND_FILE, item_id=46,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tentative], item_id=46,
        )
        rendered = render_path_claims_section(conn, 46)
        assert "(tentative)" in rendered
        assert "maybe.py" in rendered
        assert "(planned)" not in rendered

    def test_missing_materialization_state_key_renders_planned(self):
        rendered = "\n".join(_render_claim({
            "id": 100, "state": "planned", "integration_target": "main",
            "declared_targets": [{"path_string": "future.py"}],
        }))
        assert "`future.py` (planned)" in rendered
        assert "`future.py` (observed)" not in rendered

    def test_null_materialization_state_renders_planned(self):
        rendered = "\n".join(_render_claim({
            "id": 101, "state": "planned", "integration_target": "main",
            "declared_targets": [
                {"path_string": "future.py", "materialization_state": None}
            ],
        }))
        assert "`future.py` (planned)" in rendered

    def test_empty_materialization_state_renders_planned(self):
        rendered = "\n".join(_render_claim({
            "id": 102, "state": "planned", "integration_target": "main",
            "declared_targets": [
                {"path_string": "future.py", "materialization_state": ""}
            ],
        }))
        assert "`future.py` (planned)" in rendered

    def test_tentative_distinguishes_from_planned_in_same_claim(self, conn):
        actor = local_human(conn)
        planned = plan_path_target(
            conn, project_id=1,
            path_string="definite.py", kind=KIND_FILE, item_id=47,
        )
        tentative = plan_tentative_path_target(
            conn, project_id=1,
            path_string="possible.py", kind=KIND_FILE, item_id=47,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[planned, tentative], item_id=47,
        )
        rendered = render_path_claims_section(conn, 47)
        assert "definite.py` (planned)" in rendered
        assert "possible.py` (tentative)" in rendered

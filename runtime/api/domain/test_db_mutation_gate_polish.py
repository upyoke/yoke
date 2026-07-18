"""db_mutation_gate — polish gate (polishing-implementation → implemented).

Split out of ``test_db_mutation_gate.py`` to keep authored files under the
350-line limit. Also covers the seed round-trip smoke test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.db_mutation_gate import (
    check_polishing_implementation_to_implemented_gate,
)
from yoke_core.domain.db_mutation_gate_test_helpers import (
    _seed_capability,
    _seed_flow_with_migration_apply,
    _seed_project,
    _write_module,
    gate_audit_path,
    gate_db_context,
    seed_audit_row,
)
from yoke_core.domain.migration_model_capability import validate
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed


@pytest.fixture
def gate_db(tmp_path: Path):
    with gate_db_context(tmp_path) as (conn, repo_path):
        yield conn, repo_path


_PASS_VERDICT = "==== 12 passed in 1.23s ===="


class TestPolishGate:
    def _stage_with_completed_audit(self, gate_db, *, backup_path: str | None) -> tuple[int, str]:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        _seed_capability(conn, "yoke", governed_postgres_test_seed())
        _seed_flow_with_migration_apply(conn, "yoke")
        modules_dir = "runtime/api/domain/migrations"
        _write_module(repo_path, modules_dir, "demo_module")
        profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["demo_module"],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
        }
        insert_item(
            conn, id=4242, project="yoke", status="polishing-implementation",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
            test_results=_PASS_VERDICT,
        )
        # The gate's items+audit database is one per-test DB (gate_db_context);
        # migration_audit already exists there. audit_path is the path token that
        # matches init_test_db's db_path so the gate's own connection lands on
        # the same database on both backends.
        audit_path = gate_audit_path(repo_path)
        seed_audit_row(
            repo_path,
            columns=(
                "migration_name, state, project_id, model_name, "
                "backup_path, started_at"
            ),
            placeholders="?, 'completed', ?, 'primary', ?, ?",
            values=("demo_module", 1, backup_path, "2026-04-23T00:00:00Z"),
        )
        return 4242, audit_path

    def test_apply_with_extant_backup_passes(self, gate_db) -> None:
        conn, repo_path = gate_db
        backup = repo_path / "rollbacks" / "demo.sqlite"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b"backup-contents")
        item_id, audit = self._stage_with_completed_audit(
            gate_db, backup_path=str(backup),
        )
        outcome = check_polishing_implementation_to_implemented_gate(
            item_id, conn=conn, audit_db_path=audit,
        )
        assert outcome.passed, outcome.errors

    def test_apply_with_missing_backup_blocks(self, gate_db) -> None:
        conn, repo_path = gate_db
        ghost = repo_path / "rollbacks" / "ghost.sqlite"
        item_id, audit = self._stage_with_completed_audit(
            gate_db, backup_path=str(ghost),
        )
        outcome = check_polishing_implementation_to_implemented_gate(
            item_id, conn=conn, audit_db_path=audit,
        )
        assert not outcome.passed
        assert any("rollback backup missing" in e for e in outcome.errors)

    def test_apply_with_stale_in_progress_audit_blocks(self, gate_db) -> None:
        conn, repo_path = gate_db
        backup = repo_path / "rollbacks" / "demo.sqlite"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b"backup")
        item_id, audit = self._stage_with_completed_audit(
            gate_db, backup_path=str(backup),
        )
        seed_audit_row(
            repo_path,
            columns="migration_name, state, project_id, model_name, started_at",
            placeholders="?, 'live_applied', ?, 'primary', ?",
            values=("demo_module", 1, "2026-04-23T00:01:00Z"),
        )
        outcome = check_polishing_implementation_to_implemented_gate(
            item_id, conn=conn, audit_db_path=audit,
        )
        assert not outcome.passed
        assert any("stale in-progress" in e for e in outcome.errors)


class TestPolishGateTestResults:
    """The symmetric upstream half of merge_worktree_pr's CI-evidence gate.

    Polish doctrine requires polish to capture passing pytest output
    into items.test_results before advancing. Without this check items
    can reach implemented with an empty field and the merge engine
    blocks them hours later at usher time (the
    MergeBlockedNoVerificationEvidence path).

    The filter is ``command_definitions.quick`` presence
    (project-agnostic), not a hardcoded project allowlist. Projects with
    a registered quick command are enforced; projects without one pass
    through.
    """

    def _stub_quick(self, monkeypatch, command_by_project: dict[str, str | None]) -> None:
        def _fake_get_command(project_id, scope, db_path=None):
            if scope != "quick":
                return None
            return command_by_project.get(project_id)

        monkeypatch.setattr(
            "yoke_core.domain.db_mutation_gate_polish.command_definitions.get_command",
            _fake_get_command,
        )

    def test_quick_configured_passing_results_passes(self, gate_db, monkeypatch) -> None:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        self._stub_quick(monkeypatch, {"yoke": "python3 -m pytest runtime/api/"})
        insert_item(
            conn, id=5001, project="yoke", status="polishing-implementation",
            test_results=_PASS_VERDICT,
        )
        outcome = check_polishing_implementation_to_implemented_gate(5001, conn=conn)
        assert outcome.passed, outcome.errors

    def test_quick_configured_empty_results_blocks(self, gate_db, monkeypatch) -> None:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        self._stub_quick(monkeypatch, {"yoke": "python3 -m pytest runtime/api/"})
        insert_item(
            conn, id=5002, project="yoke", status="polishing-implementation",
            test_results="",
        )
        outcome = check_polishing_implementation_to_implemented_gate(5002, conn=conn)
        assert not outcome.passed
        assert any("test_results is empty" in e for e in outcome.errors)
        assert any("items.structured_field.replace" in e for e in outcome.errors)

    def test_quick_configured_failed_results_blocks(self, gate_db, monkeypatch) -> None:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        self._stub_quick(monkeypatch, {"yoke": "python3 -m pytest runtime/api/"})
        insert_item(
            conn, id=5003, project="yoke", status="polishing-implementation",
            test_results="==== 2 failed, 10 passed in 1.23s ====\nFAILED test_x",
        )
        outcome = check_polishing_implementation_to_implemented_gate(5003, conn=conn)
        assert not outcome.passed
        assert any("failure verdict" in e for e in outcome.errors)
        assert any("items.structured_field.replace" in e for e in outcome.errors)

    def test_quick_not_configured_empty_results_passes(self, gate_db, monkeypatch) -> None:
        """Project without a registered quick command passes through."""
        conn, repo_path = gate_db
        _seed_project(conn, "other", repo_path)
        self._stub_quick(monkeypatch, {})
        insert_item(
            conn, id=5004, project="other", status="polishing-implementation",
            test_results="",
        )
        outcome = check_polishing_implementation_to_implemented_gate(5004, conn=conn)
        assert outcome.passed, outcome.errors

    def test_quick_lights_up_when_externalwebapp_lands_a_quick_command(
        self, gate_db, monkeypatch
    ) -> None:
        """AC-5: filter is presence-based, not a hardcoded allowlist.

        The day any other project lands a registered ``command_definitions.quick``
        the gate begins enforcing for that project with zero code change.
        """
        conn, repo_path = gate_db
        _seed_project(conn, "externalwebapp", repo_path)
        self._stub_quick(monkeypatch, {"externalwebapp": "npx vitest run"})
        insert_item(
            conn, id=5005, project="externalwebapp", status="polishing-implementation",
            test_results="",
        )
        outcome = check_polishing_implementation_to_implemented_gate(5005, conn=conn)
        assert not outcome.passed
        assert any("test_results is empty" in e for e in outcome.errors)

    def test_quick_configured_q_mode_passing_results_passes(self, gate_db, monkeypatch) -> None:
        """YOK-1854: pytest `-q` quiet-mode test_results classifies as PASS.

        The classifier regex used to require the equals-banner pytest
        emits in normal mode, so quiet-mode captures (no surrounding
        ``=``) tripped the polish gate even when the run was green.
        Replays the YOK-1836 shape from field-note 07bde8a3.
        """
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        self._stub_quick(monkeypatch, {"yoke": "python3 -m pytest runtime/api/"})
        q_capture = (
            "....................................................................\n"
            "....................................................................\n"
            "\n"
            "454 passed in 2.13s"
        )
        insert_item(
            conn, id=5006, project="yoke", status="polishing-implementation",
            test_results=q_capture,
        )
        outcome = check_polishing_implementation_to_implemented_gate(5006, conn=conn)
        assert outcome.passed, outcome.errors

    def test_replay_su1804_shape_would_have_blocked(self, gate_db, monkeypatch) -> None:
        """AC-8: replay 2026-05-20T18:13Z / 18:41Z empty-test_results shape.

        YOK-1790, YOK-1804, YOK-1807 all reached usher with empty
        ``items.test_results`` after polish. Under the new gate, the same
        shape (project='yoke', polishing-implementation, test_results
        empty, quick configured) blocks at polish.
        """
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        self._stub_quick(monkeypatch, {"yoke": "python3 -m pytest runtime/api/"})
        insert_item(
            conn, id=5099, project="yoke", status="polishing-implementation",
            test_results="",
        )
        outcome = check_polishing_implementation_to_implemented_gate(5099, conn=conn)
        assert not outcome.passed
        assert any("test_results is empty" in e for e in outcome.errors)


# ---------------------------------------------------------------------------
# Smoke: the canonical seed itself uses the canonical capability shape
# ---------------------------------------------------------------------------


def test_governed_postgres_seed_round_trips_through_capability_validator() -> None:
    normalized = validate(governed_postgres_test_seed())
    assert normalized["default_model"] == "primary"
    assert "primary" in normalized["models"]
    primary = normalized["models"]["primary"]
    assert primary["authoritative_db"]["kind"] == "postgres"
    assert primary["validation_surface"]["kind"] == "external_validation"
    assert primary["runner"]["config"]["connection_env_var"] == "YOKE_PG_DSN"

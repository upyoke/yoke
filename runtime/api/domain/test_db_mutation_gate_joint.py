"""db_mutation_gate — joint gate (idea → refining-idea).

Split out of ``test_db_mutation_gate.py`` to keep authored files under the
350-line limit. Shared seeding helpers live in
``db_mutation_gate_test_helpers``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

import pytest

from yoke_core.domain.db_mutation_gate import (
    check_idea_to_refining_idea_gate,
)
from yoke_core.domain.db_mutation_gate_test_helpers import (
    gate_db_context,
    _seed_capability,
    _seed_flow_with_migration_apply,
    _seed_project,
    _write_module,
)
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed
from runtime.api.fixtures.backlog import insert_item


@pytest.fixture
def gate_db(tmp_path: Path):
    with gate_db_context(tmp_path) as (conn, repo_path):
        yield conn, repo_path


class TestJointGate:
    def _stage(
        self,
        gate_db,
        *,
        profile: Mapping[str, Any] | None = None,
        attestation: Mapping[str, Any] | None = None,
        seed_capability: bool = True,
        seed_flow: bool = True,
    ) -> int:
        conn, repo_path = gate_db
        _seed_project(conn, "yoke", repo_path)
        if seed_capability:
            _seed_capability(conn, "yoke", governed_postgres_test_seed())
        if seed_flow:
            _seed_flow_with_migration_apply(conn, "yoke")
        kwargs: Dict[str, Any] = {"project": "yoke"}
        if profile is not None:
            kwargs["db_mutation_profile"] = json.dumps(profile, sort_keys=True)
        if attestation is not None:
            kwargs["db_compatibility_attestation"] = json.dumps(
                attestation, sort_keys=True,
            )
        item = insert_item(conn, id=4242, status="idea", **kwargs)
        return int(item["id"])

    def test_state_none_passes(self, gate_db) -> None:
        item_id = self._stage(gate_db)
        conn, _ = gate_db
        outcome = check_idea_to_refining_idea_gate(item_id, conn=conn)
        assert outcome.passed
        assert outcome.errors == []

    def test_pre_merge_breaking_passes_without_attestation(
        self, gate_db
    ) -> None:
        # AC-10 only requires authored fields when class=pre_merge_safe.
        # A pre_merge_breaking declaration with valid model+flow+module passes.
        _conn, repo_path = gate_db
        modules_dir = "runtime/api/domain/migrations"
        _write_module(repo_path, modules_dir, "create_demo_table",
                      body="""MIGRATION = '''\nCREATE TABLE demo (id INTEGER);\n'''\n""")
        item_id = self._stage(
            gate_db,
            profile={
                "state": "declared",
                "model_name": "primary",
                "mutation_intent": "apply",
                "migration_modules": ["create_demo_table"],
                "compatibility_class": "pre_merge_breaking",
                "migration_strategy": "additive_only",
            },
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert outcome.passed, outcome.errors

    def test_pre_merge_safe_missing_attestation_blocks(self, gate_db) -> None:
        _conn, repo_path = gate_db
        modules_dir = "runtime/api/domain/migrations"
        _write_module(repo_path, modules_dir, "add_demo_col")
        item_id = self._stage(
            gate_db,
            profile={
                "state": "declared",
                "model_name": "primary",
                "mutation_intent": "apply",
                "migration_modules": ["add_demo_col"],
                "compatibility_class": "pre_merge_safe",
                "migration_strategy": "additive_only",
                "affected_surfaces": [{"table": "items"}],
            },
            attestation={},
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert not outcome.passed
        assert any("authored fields" in e for e in outcome.errors)
        assert outcome.escalations
        assert outcome.escalations[0]["from"] == "pre_merge_safe"
        assert outcome.escalations[0]["source"] == "joint_gate"

    def test_pre_merge_safe_missing_residual_risk_notes_auto_downgrades(
        self, gate_db,
    ) -> None:
        # Attestation with missing/empty residual_risk_notes triggers
        # auto-downgrade to pre_merge_breaking.  The joint gate records a
        # class_escalations entry (source=joint_gate) and refuses advance
        # until the operator either fills the field or declares
        # pre_merge_breaking explicitly.
        _conn, repo_path = gate_db
        modules_dir = "runtime/api/domain/migrations"
        _write_module(repo_path, modules_dir, "add_demo_col")
        attestation_without_risk_notes = {
            "pre_merge_readers_writers": [
                {"path": "x.py", "symbol": "f", "role": "reader"},
            ],
            "invariants": ["items.status enum exhaustive"],
            "rehearsal_commands": ["python3 -m pytest -x"],
            "residual_risk_notes": "",
        }
        item_id = self._stage(
            gate_db,
            profile={
                "state": "declared",
                "model_name": "primary",
                "mutation_intent": "apply",
                "migration_modules": ["add_demo_col"],
                "compatibility_class": "pre_merge_safe",
                "migration_strategy": "additive_only",
                "affected_surfaces": [{"table": "items"}],
            },
            attestation=attestation_without_risk_notes,
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert not outcome.passed
        assert any("residual_risk_notes" in e for e in outcome.errors)
        assert outcome.escalations
        escalation = outcome.escalations[0]
        assert escalation["from"] == "pre_merge_safe"
        assert escalation["to"] == "pre_merge_breaking"
        assert escalation["source"] == "joint_gate"

    def test_pre_merge_safe_full_attestation_passes(self, gate_db) -> None:
        _conn, repo_path = gate_db
        modules_dir = "runtime/api/domain/migrations"
        _write_module(repo_path, modules_dir, "add_demo_col")
        item_id = self._stage(
            gate_db,
            profile={
                "state": "declared",
                "model_name": "primary",
                "mutation_intent": "apply",
                "migration_modules": ["add_demo_col"],
                "compatibility_class": "pre_merge_safe",
                "migration_strategy": "additive_only",
                "schema_kinds": ["additive"],
                "affected_surfaces": [
                    {"table": "items", "columns": ["demo"]}
                ],
            },
            attestation={
                "pre_merge_readers_writers": [
                    {"path": "runtime/api/foo.py", "symbol": "load",
                     "role": "reader"},
                ],
                "invariants": ["items.status enum is exhaustive"],
                "rehearsal_commands": ["python3 -m pytest -x"],
                "residual_risk_notes": "Pre-merge readers ignore the new column.",
            },
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert outcome.passed, outcome.errors

    def test_unknown_model_blocks(self, gate_db) -> None:
        _conn, repo_path = gate_db
        item_id = self._stage(
            gate_db,
            profile={
                "state": "declared",
                "model_name": "unknown",
                "mutation_intent": "apply",
                "migration_modules": ["m"],
                "compatibility_class": "pre_merge_breaking",
                "migration_strategy": "additive_only",
            },
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert not outcome.passed
        assert any("not declared" in e for e in outcome.errors)

    def test_apply_intent_passes_when_module_file_does_not_exist_yet(
        self, gate_db
    ) -> None:
        """Refine proves intent: declared module slugs do NOT need to
        resolve to files at idea→refining-idea.  The file is authored
        during implementation.  File existence is enforced at rehearsal
        time (runner) and apply-audit evidence is enforced at
        check_implementing_to_reviewing_implementation_gate."""
        _conn, _repo = gate_db
        item_id = self._stage(
            gate_db,
            profile={
                "state": "declared",
                "model_name": "primary",
                "mutation_intent": "apply",
                "migration_modules": ["never_created"],
                "compatibility_class": "pre_merge_breaking",
                "migration_strategy": "additive_only",
            },
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert outcome.passed, outcome.errors

    def test_scanner_pattern_escalates_on_pre_merge_safe(self, gate_db) -> None:
        _conn, repo_path = gate_db
        modules_dir = "runtime/api/domain/migrations"
        _write_module(
            repo_path,
            modules_dir,
            "drops_table",
            body=(
                "MIGRATION = '''\n"
                "DROP TABLE deprecated_demo;\n"
                "'''\n"
            ),
        )
        item_id = self._stage(
            gate_db,
            profile={
                "state": "declared",
                "model_name": "primary",
                "mutation_intent": "apply",
                "migration_modules": ["drops_table"],
                "compatibility_class": "pre_merge_safe",
                "migration_strategy": "additive_only",
            },
            attestation={
                "pre_merge_readers_writers": [
                    {"path": "x.py", "symbol": "f", "role": "reader"}
                ],
                "invariants": ["i"],
                "rehearsal_commands": ["c"],
                "residual_risk_notes": "n",
            },
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert not outcome.passed
        assert any("scanner banned-pattern" in e for e in outcome.errors)
        assert any(
            esc["source"] == "scanner" for esc in outcome.escalations
        )

    def test_no_flow_with_migration_apply_blocks(self, gate_db) -> None:
        _conn, repo_path = gate_db
        modules_dir = "runtime/api/domain/migrations"
        _write_module(repo_path, modules_dir, "m")
        item_id = self._stage(
            gate_db,
            seed_flow=False,
            profile={
                "state": "declared",
                "model_name": "primary",
                "mutation_intent": "apply",
                "migration_modules": ["m"],
                "compatibility_class": "pre_merge_breaking",
                "migration_strategy": "additive_only",
            },
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert not outcome.passed
        assert any(
            "no deployment_flow" in e and "migration_apply stage" in e
            for e in outcome.errors
        )

    def test_cross_ticket_overlap_blocks(self, gate_db) -> None:
        _conn, repo_path = gate_db
        modules_dir = "runtime/api/domain/migrations"
        _write_module(repo_path, modules_dir, "m")
        candidate_profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["m"],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
            "schema_kinds": ["additive"],
            "affected_surfaces": [{"table": "items", "columns": ["x"]}],
        }
        other_profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["other"],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
            "schema_kinds": ["additive"],
            "affected_surfaces": [{"table": "items", "columns": ["x"]}],
        }
        item_id = self._stage(gate_db, profile=candidate_profile)
        # Other ticket: also non-terminal, same column.
        insert_item(
            _conn,
            id=999,
            project="yoke",
            status="implementing",
            db_mutation_profile=json.dumps(other_profile, sort_keys=True),
        )
        outcome = check_idea_to_refining_idea_gate(item_id, conn=_conn)
        assert not outcome.passed
        assert any(
            "schema-only overlap" in e and "YOK-999" in e
            for e in outcome.errors
        )

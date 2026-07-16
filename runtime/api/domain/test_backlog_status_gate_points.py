"""Guard tests for the status-gate-points map.

Two layers keep :data:`STATUS_GATE_POINTS` honest:

* the map is *derived* from the same target-set constants the gate code
  checks, so each family's coverage must equal its source constant; and
* the modules that own those constants must actually consult them on
  their gate paths (grep-level structural assertions on the source),
  so the derivation inputs cannot silently stop being the wiring.

The expected-literal test doubles as documentation: when the gate wiring
changes, it fails loudly and names exactly what the served workflow
definition now claims.
"""

from __future__ import annotations

import inspect

from yoke_core.domain import (
    backlog_architecture_gate_runner,
    backlog_authoritative_status_gate,
    backlog_db_mutation_gate_runner,
    backlog_status_gate_points as gate_points,
    path_claims_gate_boundary,
)


class TestDerivationMatchesWiringConstants:
    def _statuses_with(self, family: str) -> set:
        return {
            status
            for status, families in gate_points.STATUS_GATE_POINTS.items()
            if family in families
        }

    def test_db_claim_prose_coverage(self):
        assert self._statuses_with(gate_points.GATE_DB_CLAIM_PROSE) == set(
            backlog_db_mutation_gate_runner._PROSE_CHECK_TARGETS
        )

    def test_db_mutation_coverage(self):
        assert self._statuses_with(gate_points.GATE_DB_MUTATION) == set(
            backlog_db_mutation_gate_runner._DB_MUTATION_GATE_TARGETS
        )

    def test_architecture_impact_coverage(self):
        assert self._statuses_with(
            gate_points.GATE_ARCHITECTURE_IMPACT
        ) == set(
            backlog_architecture_gate_runner._ARCHITECTURE_GATE_TARGETS
        )

    def test_path_claim_boundary_coverage(self):
        assert self._statuses_with(
            gate_points.GATE_PATH_CLAIM_BOUNDARY
        ) == set(path_claims_gate_boundary._GATED_TARGETS)

    def test_plan_simulation_and_qa_coverage(self):
        assert self._statuses_with(gate_points.GATE_PLAN_SIMULATION) == set(
            gate_points.PLAN_SIMULATION_TARGETS
        )
        assert self._statuses_with(gate_points.GATE_QA_VERIFICATION) == set(
            gate_points.QA_VERIFICATION_TARGETS
        )


class TestComposerConsumesTheSharedConstants:
    """The composer and runners must consult the derivation inputs.

    Structural source checks: honest for a dispatch whose per-family
    filtering is distributed across four modules — the map is only
    drift-proof while each module keeps checking the constant the map
    is built from.
    """

    def test_composer_dispatches_on_the_gate_points_constants(self):
        source = inspect.getsource(backlog_authoritative_status_gate)
        assert "from .backlog_status_gate_points import" in source
        assert "in PLAN_SIMULATION_TARGETS" in source
        assert "in QA_VERIFICATION_TARGETS" in source
        # Every family's evaluator is reachable from the composer.
        for evaluator in (
            "_run_db_mutation_gate",
            "_run_architecture_impact_gate",
            "check_boundary_for_item",
            "_evaluate_plan_simulation",
            "_evaluate_qa_verification",
        ):
            assert evaluator in source, evaluator

    def test_db_mutation_runner_checks_its_target_constants(self):
        source = inspect.getsource(backlog_db_mutation_gate_runner)
        assert "target_status in _PROSE_CHECK_TARGETS" in source
        assert "_DB_MUTATION_GATE_TARGETS.get(target_status)" in source

    def test_architecture_runner_checks_its_target_constant(self):
        source = inspect.getsource(backlog_architecture_gate_runner)
        assert "target_status not in _ARCHITECTURE_GATE_TARGETS" in source

    def test_boundary_gate_checks_its_target_constant(self):
        source = inspect.getsource(path_claims_gate_boundary)
        assert "target_status not in _GATED_TARGETS" in source


def test_status_gate_points_expected_wiring():
    """The full map, spelled out. A wiring change fails here by design —
    the served workflow definition changed, and this literal names how."""
    assert dict(gate_points.STATUS_GATE_POINTS) == {
        "refining-idea": ("db_claim_prose", "db_mutation"),
        "refined-idea": ("db_claim_prose", "architecture_impact"),
        "planning": ("architecture_impact",),
        "plan-drafted": ("architecture_impact",),
        "refining-plan": ("architecture_impact",),
        "planned": (
            "db_claim_prose", "architecture_impact", "plan_simulation",
        ),
        "implementing": ("architecture_impact",),
        "reviewing-implementation": (
            "db_claim_prose", "db_mutation", "architecture_impact",
        ),
        "reviewed-implementation": (
            "architecture_impact", "path_claim_boundary", "qa_verification",
        ),
        "polishing-implementation": ("architecture_impact",),
        "implemented": (
            "db_claim_prose", "db_mutation", "architecture_impact",
            "path_claim_boundary", "qa_verification",
        ),
        "release": (
            "architecture_impact", "path_claim_boundary", "qa_verification",
        ),
        "done": ("architecture_impact", "qa_verification"),
    }

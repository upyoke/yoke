"""Bounded impact companions for the governed-migration evidence gate.

The lifecycle mutator reaches the evidence gate through its gate runner's
deferred dispatch, so a test that advances an item through
``backlog_updates`` imports nothing of the gate or of the receipt resolver
it reads. Changing either must still select those lifecycle-driven tests.
"""

MIGRATION_EVIDENCE_GATE_TESTS = (
    "runtime/api/test_migration_applied_evidence_apply.py",
    "runtime/api/domain/test_no_change_dash_close_out.py",
)

MIGRATION_EVIDENCE_GATE_SOURCE_PATHS = frozenset(
    {
        "packages/yoke-core/src/yoke_core/domain/db_mutation_gate_implementing.py",
        "packages/yoke-core/src/yoke_core/domain/db_mutation_gate_polish.py",
        "packages/yoke-core/src/yoke_core/domain/migration_rehearsal_evidence.py",
    }
)

MIGRATION_EVIDENCE_CONTRACTS = (
    (
        "migration_evidence_gate_contract",
        MIGRATION_EVIDENCE_GATE_SOURCE_PATHS,
        MIGRATION_EVIDENCE_GATE_TESTS,
    ),
)

__all__ = [
    "MIGRATION_EVIDENCE_CONTRACTS",
    "MIGRATION_EVIDENCE_GATE_SOURCE_PATHS",
    "MIGRATION_EVIDENCE_GATE_TESTS",
]

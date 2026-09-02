"""Repo-relative path families whose files name a retired term on purpose.

Each tuple is a prefix list: a file whose path starts with one of these
entries is exempt from the pattern that names the tuple, because that file's
subject IS the retirement. The engine-side equivalent for audit
infrastructure is :mod:`doctor_hc_obsoleted_terms_allowlists`; these families
are specific to the Yoke source tree, so they live in the project.
"""

from __future__ import annotations

#: The history entry that STRIPS a retired surface, its test, and the event
#: registry row that marks the emitter retired all have to name it.
#: Historical ledger rows must keep resolving.
MIGRATION_RETIREMENT_SUBJECT_PATHS: tuple[str, ...] = (
    "packages/yoke-core/src/yoke_core/domain/migrations/",
    "runtime/api/domain/test_drop_migration_apply_stages_migration.py",
    "packages/yoke-core/src/yoke_core/domain/populate_registry_data_authoritative.py",
    # The generated catalog's RETIRED rows name the emitter they retire, so
    # historical ledger rows stay attributable.
    "docs/event-catalog.md",
)

#: Surfaces that keep the retired QA column spellings on purpose. The history
#: entry that renames the columns names them as its subject, and the
#: immutable workflow-definition canon plus its tests carry a *different*
#: retirement wearing the same word — the skill-binding vocabulary an earlier
#: entry replaced — which one column-name pattern cannot tell apart from the
#: QA one. The agent packet warns the next agent off the retired spellings by
#: name — teaching that cannot be done without writing them down.
QA_PACKET_TEACHING_PATHS: tuple[str, ...] = (
    "packages/yoke-core/src/yoke_core/domain/schema_api_context_tables_qa.py",
)

QA_RUNNER_RENAME_SUBJECT_PATHS: tuple[str, ...] = (
    "packages/yoke-core/src/yoke_core/domain/migrations/",
    "runtime/api/domain/test_migration_qa_runner_identity_columns.py",
    "runtime/api/domain/test_builtin_workflow_version_reconvergence.py",
    "runtime/api/domain/test_workflow_and_deployment_stage_vocabulary_migration.py",
)

__all__ = [
    "MIGRATION_RETIREMENT_SUBJECT_PATHS",
    "QA_PACKET_TEACHING_PATHS",
    "QA_RUNNER_RENAME_SUBJECT_PATHS",
]

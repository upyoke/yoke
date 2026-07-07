"""Residue scan for fixture helpers consuming the derived items DDL.

The fixture helper family that migrated onto
``runtime/api/fixtures/schema_ddl_items`` must not regress back to copied
long-form realistic ``items`` DDL. Helpers are scanned for
``CREATE TABLE items`` blocks; any new long-form realistic copy fails.
Helpers that intentionally retain a minimal or relaxed ``items`` shape are
explicitly exempted with a one-line reason — this keeps the rationale
visible in code review rather than buried in the spec.

Derivation-correctness coverage for the DDL itself lives in
``runtime/api/test_schema_fixture_derivation.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yoke_core.domain import (
    migration_apply_test_helpers,
    render_body_test_helpers,
)
from yoke_core.engines import (
    _doctor_db_test_helpers,
    _doctor_hc_meta_full_test_helpers,
    _doctor_meta_test_helpers,
    _resync_full_test_helpers,
    _resync_test_helpers,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _module_rel(module: object) -> str:
    path = Path(module.__file__).resolve()
    return path.relative_to(REPO_ROOT).as_posix()


# Helpers that consume the canonical-derived items DDL through
# ``_ITEMS_DDL`` (or ``_ITEMS_RELAXED_DDL``). The residue scan refuses
# any new copied realistic ``CREATE TABLE items`` block in these files.
_MIGRATED_HELPERS = (
    "runtime/api/fixtures/schema_ddl_items.py",
    "runtime/api/fixtures/schema_ddl.py",
    "runtime/api/parity_db_router_test_fixtures.py",
    _module_rel(_doctor_meta_test_helpers),
    _module_rel(render_body_test_helpers),
    "runtime/api/events_crud_test_fixtures.py",
    "runtime/api/fixtures/canonical_db.py",
)


# Helpers that intentionally retain a minimal or relaxed ``items``
# shape. Each entry pairs the path with the exemption reason so the
# rationale ships with the code. Future migrations of these helpers
# would move them out of ``_EXEMPT_HELPERS`` and into
# ``_MIGRATED_HELPERS``.
_EXEMPT_HELPERS: dict[str, str] = {
    # Helper carries a 3-column ``items`` placeholder for the
    # validation-surface DB; production seeders are exercised in their
    # own test files. Adopting canonical shape is unnecessary surface
    # for this fixture's job.
    _module_rel(migration_apply_test_helpers):
        "validation-surface placeholder; intentional 3-column items table",
    # Helper shares its ITEMS_SCHEMA via test_dependency_schema, which
    # deliberately omits CHECK constraints so a few API tests can seed
    # legacy/invalid statuses to verify startup guards.
    "runtime/api/scheduler_test_fixtures.py":
        "uses test_dependency_schema.ITEMS_SCHEMA (intentionally CHECK-less)",
    # Doctor-DB health checks query a slim column subset and the tests
    # consuming this helper insert rows without created_at/updated_at;
    # canonical NOT NULL constraints would require coordinated edits to
    # sibling test setup.
    _module_rel(_doctor_db_test_helpers):
        "slim-shape items for doctor-DB HC tests; relaxed inserts",
    # Helper is consumed by test_doctor_hc_meta_full_migration, which
    # simulates pre-/post-migration column states via ALTER TABLE; that
    # simulation conflicts with canonical-shape DDL (governance columns
    # already present). Documented exemption pending coordinated test
    # refactor.
    _module_rel(_doctor_hc_meta_full_test_helpers):
        "pre-/post-migration column simulation conflicts with canonical shape",
    # Resync helpers expose a minimal items shape for resync HC drift
    # tests; their consuming tests insert rows without canonical NOT
    # NULL fields.
    _module_rel(_resync_test_helpers):
        "slim-shape items for resync drift tests; relaxed inserts",
    _module_rel(_resync_full_test_helpers):
        "slim-shape items for resync_full drift tests; relaxed inserts",
    # Board fixtures expose a board-specific items shape (includes
    # ``progress`` and omits canonical structured fields) tuned to
    # widget rendering tests.
    "runtime/api/board/tests/conftest.py":
        "board-specific items shape; includes progress column",
}


# Lines/blocks that legitimately mention ``CREATE TABLE items`` without
# being a long-form realistic DDL copy: the canonical derivation source
# itself, the production schema init, and so on. These are excluded
# from the residue scan because they're either the source of truth or
# the documentation of past migrations.
_RESIDUE_SCAN_EXCLUDES = (
    "runtime/api/fixtures/schema_ddl_items.py",  # the derivation home
    "runtime/api/fixtures/schema_ddl.py",        # facade
)
_RESIDUE_SCAN_HELPERS = tuple(
    path for path in _MIGRATED_HELPERS
    if path not in _RESIDUE_SCAN_EXCLUDES
)


# Match a CREATE TABLE statement for ``items`` regardless of casing /
# IF NOT EXISTS. Capture the body so we can length-check it.
_ITEMS_DDL_BLOCK = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?items\s*\((?P<body>[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)


def _is_long_form_realistic(body: str) -> bool:
    """Heuristic: a copied realistic items DDL has many columns and
    references several canonical structured fields. Tiny minimal
    placeholder shapes (a few columns) are not flagged.
    """
    cols = [c.strip() for c in body.split(",") if c.strip()]
    if len(cols) < 8:
        return False
    canonical_field_markers = (
        "spec ",
        "design_spec ",
        "technical_plan ",
        "shepherd_log ",
        "test_results ",
        "deploy_log ",
        "browser_qa_metadata ",
        "db_mutation_profile ",
        "db_compatibility_attestation ",
    )
    body_lower = body.lower()
    return any(marker in body_lower for marker in canonical_field_markers)


class TestResidueScan:
    """Migrated helpers must not regress to copied long-form realistic DDL."""

    @pytest.mark.parametrize("rel_path", _RESIDUE_SCAN_HELPERS)
    def test_no_long_form_items_copy(self, rel_path: str) -> None:
        path = REPO_ROOT / rel_path
        assert path.exists(), f"Migrated helper missing: {rel_path}"
        text = path.read_text(encoding="utf-8")
        for match in _ITEMS_DDL_BLOCK.finditer(text):
            body = match.group("body")
            assert not _is_long_form_realistic(body), (
                f"{rel_path} reintroduced a long-form realistic items DDL "
                "block; consume _ITEMS_DDL or _ITEMS_RELAXED_DDL from "
                "runtime.api.fixtures.schema_ddl_items instead."
            )

    def test_exemptions_listed_with_reasons(self) -> None:
        """Each exempt helper must carry a non-empty reason."""
        assert _EXEMPT_HELPERS, "Exemption catalog cannot be empty"
        for path, reason in _EXEMPT_HELPERS.items():
            assert reason.strip(), (
                f"Residue exemption for {path!r} missing reason"
            )
            full = REPO_ROOT / path
            assert full.exists(), (
                f"Exempt helper path no longer exists: {path}"
            )

    def test_helper_family_complete(self) -> None:
        """Every helper in the fixture-schema scope is either migrated or
        explicitly exempted — no helper goes silently uncategorized.
        """
        path_claim_files = (
            "runtime/api/fixtures/schema_ddl_items.py",
            "runtime/api/fixtures/schema_ddl.py",
            "runtime/api/fixtures/canonical_db.py",
            "runtime/api/parity_db_router_test_fixtures.py",
            "runtime/api/scheduler_test_fixtures.py",
            "runtime/api/events_crud_test_fixtures.py",
            _module_rel(migration_apply_test_helpers),
            "runtime/api/board/tests/conftest.py",
            _module_rel(_resync_test_helpers),
            _module_rel(_resync_full_test_helpers),
            _module_rel(_doctor_db_test_helpers),
            _module_rel(_doctor_meta_test_helpers),
            _module_rel(_doctor_hc_meta_full_test_helpers),
            _module_rel(render_body_test_helpers),
        )
        categorized = set(_MIGRATED_HELPERS) | set(_EXEMPT_HELPERS)
        uncategorized = [p for p in path_claim_files if p not in categorized]
        assert not uncategorized, (
            "Fixture-schema helpers missing from categorization: "
            f"{uncategorized}"
        )

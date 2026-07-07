"""Coverage for idea readiness File Budget path extraction.

Sibling of ``test_idea_readiness_check.py`` — kept apart so the parent
test file stays at its existing line budget. Locks the shared File
Budget path language used by idea readiness and path-claim coverage.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.idea_readiness_check import (
    _extract_file_budget_paths,
    verify_file_budget_claim_consistency,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


_SCHEMA = """
CREATE TABLE items (id INTEGER PRIMARY KEY, spec TEXT);
CREATE TABLE path_claims (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    state TEXT
);
CREATE TABLE path_targets (
    id INTEGER PRIMARY KEY,
    path_string TEXT,
    kind TEXT
);
CREATE TABLE path_claim_targets (
    claim_id INTEGER,
    target_id INTEGER
);
"""


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA)
    finally:
        conn.close()


@pytest.fixture
def conn_with_claim(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn, "(unused)"
        finally:
            conn.close()


def test_broadened_paths_recognized(conn_with_claim):
    """Top-level ALLCAPS docs, strategy/, and json/yaml/toml/sh
    extensions are matched by the File Budget extractor — not just
    py/md under runtime/docs/.agents/projects/templates/browser."""
    conn, _ = conn_with_claim
    p = _p(conn)
    spec = (
        "## File Budget\n\n"
        "- `AGENTS.md` — promote rule to structural enforcement\n"
        "- `.yoke/strategy/WISPS.md` — flip WISP-31 state\n"
        "- `runtime/harness/claude/settings.json` — hook wire-up\n"
        "- `runtime/harness/codex/hooks.json` — Codex wire-up\n"
        "- `runtime/api/domain/foo.py` — new helper\n"
    )
    conn.execute(f"INSERT INTO items (id, spec) VALUES (1, {p})", (spec,))
    conn.execute(
        "INSERT INTO path_claims VALUES (10, 1, 'planned')"
    )
    for tid, path in (
        (1, "AGENTS.md"),
        (2, ".yoke/strategy/WISPS.md"),
        (3, "runtime/harness/claude/settings.json"),
        (4, "runtime/harness/codex/hooks.json"),
        (5, "runtime/api/domain/foo.py"),
    ):
        conn.execute(
            f"INSERT INTO path_targets VALUES ({p}, {p}, 'file')",
            (tid, path),
        )
        conn.execute(
            f"INSERT INTO path_claim_targets VALUES (10, {p})", (tid,),
        )
    conn.commit()
    issues = verify_file_budget_claim_consistency(conn, 1)
    assert issues == [], (
        f"expected all five paths recognized; got remediation: {issues}"
    )


def test_lowercase_top_level_filename_still_ignored(conn_with_claim):
    """Lower-cased top-level paths (e.g. ``readme.md``, ``config.toml``)
    stay outside the recognized set unless they are dotfiles."""
    conn, _ = conn_with_claim
    p = _p(conn)
    spec = (
        "## File Budget\n\n"
        "- `readme.md` — lowercase, intentionally not matched\n"
        "- `runtime/api/domain/foo.py` — anchor\n"
    )
    conn.execute(f"INSERT INTO items (id, spec) VALUES (1, {p})", (spec,))
    conn.execute("INSERT INTO path_claims VALUES (10, 1, 'planned')")
    conn.execute(
        "INSERT INTO path_targets VALUES (1, 'runtime/api/domain/foo.py', 'file')"
    )
    conn.execute("INSERT INTO path_claim_targets VALUES (10, 1)")
    conn.commit()
    # lowercase readme.md is not declared in claim, and not extracted
    # from the budget — claim-vs-budget consistency holds because both
    # sides agree on the empty-or-py-only set.
    issues = verify_file_budget_claim_consistency(conn, 1)
    assert issues == []


def test_top_level_dotfile_passes_consistency(conn_with_claim):
    """YOK-1710 reproduction: `.gitignore` in both the File Budget and
    planned path claim must not report `CLAIM_NOT_IN_FILE_BUDGET`."""
    conn, _ = conn_with_claim
    p = _p(conn)
    spec = (
        "## File Budget\n\n"
        "- `.gitignore` — remove stale generated-view ignore rule.\n"
        "- `runtime/api/domain/designs.py` — remove retired command.\n"
    )
    conn.execute(f"INSERT INTO items (id, spec) VALUES (1, {p})", (spec,))
    conn.execute("INSERT INTO path_claims VALUES (10, 1, 'planned')")
    for tid, path in (
        (1, ".gitignore"),
        (2, "runtime/api/domain/designs.py"),
    ):
        conn.execute(
            f"INSERT INTO path_targets VALUES ({p}, {p}, 'file')",
            (tid, path),
        )
        conn.execute(
            f"INSERT INTO path_claim_targets VALUES (10, {p})", (tid,),
        )
    conn.commit()

    issues = verify_file_budget_claim_consistency(conn, 1)
    assert issues == []
    extracted = _extract_file_budget_paths(spec)
    assert ".gitignore" in extracted


def test_file_budget_section_extends_through_level3_subheadings(
    conn_with_claim,
):
    """A ``## File Budget`` section that uses ``### Subheading`` blocks
    must capture path declarations from every subsection, and the section
    must still terminate at the next ``## `` (level-2) heading.
    """
    conn, _ = conn_with_claim
    p = _p(conn)
    spec = (
        "## File Budget\n\n"
        "### Current file-size pressure\n\n"
        "- `runtime/api/domain/alpha.py` — under first subheading\n\n"
        "### Sibling-module plan\n\n"
        "- `runtime/api/domain/beta.py` — under second subheading\n\n"
        "### File-by-file edit summary\n\n"
        "- `runtime/api/domain/gamma.py` — under third subheading\n\n"
        "## Acceptance Criteria\n\n"
        "- `runtime/api/domain/never_in_budget.py` — outside section\n"
    )
    conn.execute(f"INSERT INTO items (id, spec) VALUES (1, {p})", (spec,))
    conn.execute("INSERT INTO path_claims VALUES (10, 1, 'planned')")
    declared = (
        (1, "runtime/api/domain/alpha.py"),
        (2, "runtime/api/domain/beta.py"),
        (3, "runtime/api/domain/gamma.py"),
    )
    for tid, path in declared:
        conn.execute(
            f"INSERT INTO path_targets VALUES ({p}, {p}, 'file')",
            (tid, path),
        )
        conn.execute(
            f"INSERT INTO path_claim_targets VALUES (10, {p})", (tid,),
        )
    conn.commit()
    issues = verify_file_budget_claim_consistency(conn, 1)
    assert issues == [], (
        f"expected all three under-### paths recognized; got: {issues}"
    )

    extracted = _extract_file_budget_paths(spec)
    assert extracted == {
        "runtime/api/domain/alpha.py",
        "runtime/api/domain/beta.py",
        "runtime/api/domain/gamma.py",
    }, (
        "section must extend through ### subheadings and stop at the "
        f"next ## heading; got {extracted}"
    )


def test_extensionless_project_policy_passes_consistency(conn_with_claim):
    """reproduction: File Budget lists `.yoke/lint-config`, the active
    path claim declares the same file, and `idea_readiness_check` claim
    consistency must pass instead of reporting `CLAIM_NOT_IN_FILE_BUDGET`."""
    conn, _ = conn_with_claim
    p = _p(conn)
    spec = (
        "## File Budget\n\n"
        "- `.yoke/lint-config` — project policy knob.\n"
        "- `runtime/api/domain/foo.py` — call site.\n"
    )
    conn.execute(f"INSERT INTO items (id, spec) VALUES (1, {p})", (spec,))
    conn.execute("INSERT INTO path_claims VALUES (10, 1, 'planned')")
    for tid, path in (
        (1, ".yoke/lint-config"),
        (2, "runtime/api/domain/foo.py"),
    ):
        conn.execute(
            f"INSERT INTO path_targets VALUES ({p}, {p}, 'file')",
            (tid, path),
        )
        conn.execute(
            f"INSERT INTO path_claim_targets VALUES (10, {p})", (tid,),
        )
    conn.commit()

    issues = verify_file_budget_claim_consistency(conn, 1)
    assert issues == [], (
        "extensionless `.yoke/lint-config` must be visible to readiness so "
        f"the YOK-1602 shape no longer false-positives; got: {issues}"
    )
    extracted = _extract_file_budget_paths(spec)
    assert ".yoke/lint-config" in extracted

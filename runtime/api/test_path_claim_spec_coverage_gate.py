"""Tests for path_claim_spec_coverage_gate.

Covers the parser + the evaluate() integration: pass when claim covers
File Budget, block when it does not, no-op when no claim or no spec.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_backend
from yoke_core.domain.actors import seed_canonical_actors, seed_human_actor
from yoke_core.domain.path_claim_spec_coverage_gate import (
    CoverageResult,
    evaluate,
    extract_file_budget_paths,
)
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import (
    create_path_registry_tables,
)
from yoke_core.domain.schema_init_tables import create_core_tables


@pytest.fixture
def conn(monkeypatch):
    name = pg_testdb.create_test_database()
    monkeypatch.setenv(
        db_backend.PG_DSN_ENV, pg_testdb.dsn_for_test_database(name)
    )
    c = pg_testdb.connect_test_database(name)
    create_core_tables(c)
    create_path_registry_tables(c)
    create_actor_path_claim_tables(c)
    seed_canonical_actors(c)
    c.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at) "
        "VALUES (1, 'yoke', 'yoke', 'YOK', "
        "'2026-05-01T00:00:00Z') "
        "ON CONFLICT(id) DO NOTHING"
    )
    c.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (1, 'snap-base', '2026-05-01T00:00:00Z')"
    )
    c.commit()
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _seed_item(conn, *, item_id: int = 5001, spec: str = "") -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'refined-idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    if spec:
        conn.execute(
            "INSERT INTO item_sections (item_id, section_name, content, "
            "created_at, updated_at) VALUES (%s, 'spec', %s, "
            "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
            (item_id, spec),
        )
    conn.commit()
    return item_id


def _seed_target(conn, path_string: str) -> int:
    cur = conn.execute(
        "INSERT INTO path_targets (project_id, path_string, kind, "
        "generation, created_at) "
        "VALUES (1, %s, 'file', 0, '2026-05-01T00:00:00Z') "
        "RETURNING id",
        (path_string,),
    )
    target_id = int(cur.fetchone()[0])
    conn.commit()
    return target_id


def _seed_active_claim(
    conn,
    *,
    item_id: int,
    actor_id: int,
    target_ids: list[int],
) -> int:
    cur = conn.execute(
        "INSERT INTO path_claims (state, mode, actor_id, item_id, "
        "integration_target, base_commit_sha, registered_at, "
        "activated_at) "
        "VALUES ('active', 'exclusive', %s, %s, 'main', 'snap-base', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z') RETURNING id",
        (actor_id, item_id),
    )
    claim_id = int(cur.fetchone()[0])
    for target_id in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, "
            "declared_at) VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (claim_id, target_id),
        )
    conn.commit()
    return claim_id


# -------- parser tests --------

class TestExtractFileBudgetPaths:
    def test_extracts_from_basic_section(self):
        spec = """# Spec

## File Budget

- Hard limit: 350 lines.
- Expected implementation shape:
  - `runtime/api/domain/foo.py` — does X.
  - `runtime/api/test_foo.py` — covers AC-1.
  - `docs/lifecycle.md` — operator note.
"""
        paths = extract_file_budget_paths(spec)
        assert paths == [
            "runtime/api/domain/foo.py",
            "runtime/api/test_foo.py",
            "docs/lifecycle.md",
        ]

    def test_skips_inline_function_and_shell_tokens(self):
        spec = """## File Budget

- Expected implementation shape:
  - `runtime/api/domain/sessions.py` — calls `release_item_claim` and
    replaces `>/dev/null 2>&1 || true`.
"""
        # release_item_claim has no /, shell fragment fails safe-token parsing.
        # Only sessions.py should survive.
        paths = extract_file_budget_paths(spec)
        assert paths == ["runtime/api/domain/sessions.py"]

    def test_picks_up_multiple_paths_per_line(self):
        spec = """## File Budget

  - Tests: `runtime/api/test_foo.py` and/or `runtime/api/test_bar.py`.
"""
        paths = extract_file_budget_paths(spec)
        assert paths == [
            "runtime/api/test_foo.py",
            "runtime/api/test_bar.py",
        ]

    def test_dedupes(self):
        spec = """## File Budget

  - `a/b.py` — first.
  - `a/b.py` — second.
"""
        assert extract_file_budget_paths(spec) == ["a/b.py"]

    def test_returns_empty_when_no_section(self):
        assert extract_file_budget_paths("# title\n\nbody") == []

    def test_returns_empty_when_section_has_no_paths(self):
        spec = """## File Budget

- Hard limit: 350 lines.
- Design target: 300 lines.
"""
        assert extract_file_budget_paths(spec) == []

    def test_stops_at_next_section(self):
        spec = """## File Budget

- `a/b.py` — in budget.

## Another Section

- `c/d.py` — should not appear.
"""
        assert extract_file_budget_paths(spec) == ["a/b.py"]

    def test_handles_empty_string(self):
        assert extract_file_budget_paths("") == []

    def test_extensionless_project_policy_extracted(self):
        """extensionless paths such as ``.yoke/lint-config`` are
        first-class File Budget tokens, not just extensioned files."""
        spec = (
            "## File Budget\n\n"
            "- `.yoke/lint-config` — config knob being widened.\n"
            "- `runtime/api/domain/foo.py` — call site.\n"
        )
        assert extract_file_budget_paths(spec) == [
            ".yoke/lint-config",
            "runtime/api/domain/foo.py",
        ]


class TestSharedParserParity:
    """AC-2 parity: idea_readiness_check and path_claim_spec_coverage_gate
    must use one shared File Budget parser. The compatibility wrapper
    inside ``idea_readiness_check`` delegates to the shared module without
    owning a second regex allowlist; both surfaces must accept identical
    extensionless paths.
    """

    def test_both_surfaces_share_the_same_function_object(self):
        from yoke_core.domain import file_budget_paths as shared
        from yoke_core.domain import idea_readiness_check as readiness
        from yoke_core.domain import path_claim_spec_coverage_gate as gate

        assert (
            gate.extract_file_budget_paths
            is shared.extract_file_budget_paths
        ), (
            "the gate's public extract_file_budget_paths must be the "
            "shared symbol — no second regex allowlist allowed"
        )
        # readiness exposes a set-shaped wrapper (legacy API); it must
        # delegate to the shared set-helper, not to a private regex.
        assert (
            readiness._extract_file_budget_paths
            is shared.extract_file_budget_paths_set
        ), (
            "readiness._extract_file_budget_paths must alias the shared "
            "set-helper — no divergent local extractor"
        )

    def test_both_surfaces_accept_project_lint_config(self):
        """Parity proof for the reproduction: both code paths
        recognize extensionless ``.yoke/lint-config`` in the File Budget."""
        from yoke_core.domain.idea_readiness_check import (
            _extract_file_budget_paths as readiness_extract,
        )
        spec = (
            "## File Budget\n\n"
            "- `.yoke/lint-config` — extensionless target.\n"
            "- `runtime/api/domain/foo.py` — extensioned anchor.\n"
        )
        gate_paths = set(extract_file_budget_paths(spec))
        readiness_paths = readiness_extract(spec)
        assert ".yoke/lint-config" in gate_paths
        assert ".yoke/lint-config" in readiness_paths
        assert gate_paths == readiness_paths


# -------- evaluate() tests --------

class TestEvaluate:
    def test_pass_when_claim_covers_all_budget(self, conn):
        actor = seed_human_actor(conn)
        item_id = _seed_item(
            conn,
            spec=(
                "## File Budget\n\n"
                "- `runtime/api/domain/foo.py` — does X.\n"
                "- `docs/lifecycle.md` — note.\n"
            ),
        )
        t1 = _seed_target(conn, "runtime/api/domain/foo.py")
        t2 = _seed_target(conn, "docs/lifecycle.md")
        claim_id = _seed_active_claim(
            conn, item_id=item_id, actor_id=actor, target_ids=[t1, t2],
        )

        result = evaluate(item_id, conn=conn)

        assert isinstance(result, CoverageResult)
        assert result.is_blocked is False
        assert result.missing_paths == []
        assert result.active_claim_ids == [claim_id]
        assert set(result.claim_paths) == {
            "runtime/api/domain/foo.py", "docs/lifecycle.md",
        }
        assert result.no_claims is False

    def test_block_when_budget_lists_path_not_in_claim(self, conn):
        actor = seed_human_actor(conn)
        item_id = _seed_item(
            conn,
            spec=(
                "## File Budget\n\n"
                "- `runtime/api/domain/foo.py` — covered.\n"
                "- `runtime/api/domain/bar.py` — DEFERRED, not in claim.\n"
            ),
        )
        t1 = _seed_target(conn, "runtime/api/domain/foo.py")
        _seed_active_claim(
            conn, item_id=item_id, actor_id=actor, target_ids=[t1],
        )

        result = evaluate(item_id, conn=conn)

        assert result.is_blocked is True
        assert result.missing_paths == ["runtime/api/domain/bar.py"]

    def test_noop_when_no_claim_rows(self, conn):
        item_id = _seed_item(
            conn,
            spec="## File Budget\n\n- `a/b.py` — alone.\n",
        )

        result = evaluate(item_id, conn=conn)

        assert result.is_blocked is False
        assert result.no_claims is True
        assert result.active_claim_ids == []
        assert result.file_budget_paths == ["a/b.py"]

    def test_noop_when_spec_has_no_file_budget(self, conn):
        actor = seed_human_actor(conn)
        item_id = _seed_item(conn, spec="## Source\n\nrandom text")
        t1 = _seed_target(conn, "runtime/api/domain/foo.py")
        _seed_active_claim(
            conn, item_id=item_id, actor_id=actor, target_ids=[t1],
        )

        result = evaluate(item_id, conn=conn)

        assert result.is_blocked is False
        assert result.file_budget_paths == []
        assert result.missing_paths == []

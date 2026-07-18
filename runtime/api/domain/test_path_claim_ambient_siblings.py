"""Ambient sibling-claim view coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain._path_claims_test_helpers import (
    conn,  # noqa: F401  (pytest fixture)
    local_human,
    seed_target,
)
from yoke_core.domain.path_claim_ambient_siblings import (
    AmbientSiblingRow,
    fetch_rows,
    render,
)
from yoke_core.domain.path_claims import register


def _seed_item(conn, *, item_id: int, title: str, project: str = "yoke") -> None:
    project_id = 2 if project == "externalwebapp" else int(project) if str(project).isdigit() else 1
    conn.execute(
        "INSERT INTO items (id, title, status, project_id, project_sequence, type, "
        "                   created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            item_id,
            title,
            "implementing",
            project_id,
            item_id,
            "issue",
            "2026-05-01T00:00:00Z",
            "2026-05-01T00:00:00Z",
        ),
    )


class TestFetchRows:
    def test_returns_non_terminal_siblings(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=100, title="alpha")
        _seed_item(conn, item_id=101, title="beta")
        a_target = seed_target(conn, path_string="runtime/api/alpha")
        b_target = seed_target(conn, path_string="runtime/api/beta")
        a_claim = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[a_target],
            item_id=100,
        )
        b_claim = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[b_target],
            item_id=101,
        )

        rows = fetch_rows(integration_target="main", conn=conn)
        ids = [r.claim_id for r in rows]
        assert a_claim in ids
        assert b_claim in ids

    def test_excludes_self_via_exclude_claim_id(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=100, title="alpha")
        _seed_item(conn, item_id=101, title="beta")
        a_target = seed_target(conn, path_string="runtime/api/alpha")
        b_target = seed_target(conn, path_string="runtime/api/beta")
        a_claim = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[a_target], item_id=100,
        )
        b_claim = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[b_target], item_id=101,
        )

        rows = fetch_rows(
            integration_target="main", exclude_claim_id=a_claim, conn=conn
        )
        ids = [r.claim_id for r in rows]
        assert a_claim not in ids
        assert b_claim in ids

    def test_other_target_excluded(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=100, title="alpha")
        _seed_item(conn, item_id=101, title="beta")
        main_target = seed_target(conn, path_string="runtime/api/alpha")
        feature_target = seed_target(conn, path_string="runtime/api/beta")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[main_target], item_id=100,
        )
        register(
            conn, actor_id=actor, integration_target="feature-x",
            target_ids=[feature_target], item_id=101,
        )

        rows = fetch_rows(integration_target="main", conn=conn)
        items = [r.item_id for r in rows]
        assert 100 in items
        assert 101 not in items

    def test_terminal_states_excluded(self, conn):
        from yoke_core.domain.path_claims import release

        actor = local_human(conn)
        _seed_item(conn, item_id=100, title="alpha")
        target = seed_target(conn, path_string="runtime/api/alpha")
        claim_id = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=100,
        )
        release(conn, claim_id=claim_id, reason="done")

        rows = fetch_rows(integration_target="main", conn=conn)
        ids = [r.claim_id for r in rows]
        assert claim_id not in ids


class TestCoverageTruncation:
    def test_top_three_plus_extra_count(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=100, title="alpha")
        targets = [
            seed_target(conn, path_string=f"runtime/api/path_{i}")
            for i in range(5)
        ]
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=targets, item_id=100,
        )
        rows = fetch_rows(integration_target="main", conn=conn)
        assert len(rows) == 1
        row = rows[0]
        assert len(row.coverage_paths) == 3
        assert row.extra_count == 2


class TestRender:
    def test_render_fits_80_columns(self, conn):
        actor = local_human(conn)
        _seed_item(
            conn,
            item_id=100,
            title="A reasonably long ticket title that should still fit",
        )
        target = seed_target(conn, path_string="runtime/api/domain")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=100,
        )
        rendered = render("main", conn=conn)
        assert "Sibling Path Claims" in rendered
        for line in rendered.splitlines():
            # Allow the section header to extend slightly; coverage
            # rows must fit in 80 columns.
            if line.startswith("###") or line.startswith("```"):
                continue
            assert len(line) <= 80, f"line too long: {line!r}"

    def test_render_empty_when_no_siblings(self, conn):
        rendered = render("main", conn=conn)
        assert rendered == ""

    def test_render_includes_state_and_item_id(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=100, title="alpha")
        target = seed_target(conn, path_string="runtime/api/alpha")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=100,
        )
        rendered = render("main", conn=conn)
        assert "YOK-100" in rendered
        assert "planned" in rendered or "active" in rendered or "blocked" in rendered


class TestAgeHints:
    """Smoke-coverage of the age-hint computation."""

    def test_unknown_when_snapshot_missing(self, conn):
        actor = local_human(conn)
        _seed_item(conn, item_id=100, title="alpha")
        target = seed_target(conn, path_string="runtime/api/alpha")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=100,
        )
        rows = fetch_rows(integration_target="main", conn=conn)
        # Planned state has no base_commit_sha; hint defaults to "unknown".
        assert rows[0].base_commit_age_hint == "unknown"

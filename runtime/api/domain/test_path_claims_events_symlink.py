"""Coverage for symlink-canonicalization event emission.

The events ride on the canonical :func:`yoke_core.domain.events.emit_event`
path. These tests assert payload shape, severity, and claim_id presence
when registration successfully pairs a symlink with its canonical
target — including the reused-claim path in
:func:`yoke_core.domain.path_claims_register.register_for_item`.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import db_backend
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
)
from yoke_core.domain.path_claims_symlink_expansion import (
    SYMLINK_CANONICALIZED,
)
from yoke_core.domain.path_claims_events_symlink import (
    emit_symlink_canonicalized,
    emit_symlink_skipped,
)
from runtime.api.fixtures.machine_config_test import (
    clear_machine_checkout,
    register_machine_checkout,
)


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_id(value: str | int) -> int:
    text = str(value)
    return int(text) if text.isdigit() else {"yoke": 1, "buzz": 2}.get(text, 1)


def _seed_project_row(
    conn, *, project_id: str | int, repo_path: str = ""
) -> None:
    """Insert a minimal ``projects`` row for the registration on-ramp."""
    p = _placeholder(conn)
    numeric_id = _project_id(project_id)
    slug = (
        str(project_id)
        if not str(project_id).isdigit()
        else {1: "yoke", 2: "buzz"}.get(numeric_id, f"project-{numeric_id}")
    )
    checkout = Path(repo_path)
    if repo_path and checkout.is_dir():
        register_machine_checkout(checkout.parent, checkout, numeric_id)
    else:
        clear_machine_checkout(numeric_id)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, default_branch, github_repo, "
        "public_item_prefix, created_at) "
        f"VALUES ({p}, {p}, {p}, 'main', NULL, 'YOK', "
        "'2026-05-11T00:00:00Z') "
        "ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug",
        (numeric_id, slug, slug.title()),
    )


def _seed_item(conn, *, item_id: int, project: str) -> None:
    p = _placeholder(conn)
    conn.execute(f"DELETE FROM items WHERE id = {p}", (item_id,))
    project_id = _project_id(project)
    conn.execute(
        "INSERT INTO items "
        "(id, title, status, type, project_id, project_sequence, "
        "created_at, updated_at) "
        f"VALUES ({p}, {p}, 'idea', 'issue', {p}, {p}, "
        "'2026-05-11T00:00:00Z', '2026-05-11T00:00:00Z')",
        (item_id, f"Test item {item_id}", project_id, item_id),
    )


def _seed_symlink_fact(conn, *, project_id: int = 1) -> None:
    p = _placeholder(conn)
    row = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        f"VALUES ({p}, 'sha-symlink', '2026-05-11T00:00:00Z') "
        "RETURNING id",
        (project_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO path_snapshot_symlink_facts "
        "(snapshot_id, symlink_path, reason, target_attempt, canonical_path) "
        f"VALUES ({p}, 'CLAUDE.md', {p}, 'AGENTS.md', 'AGENTS.md')",
        (int(row[0]), SYMLINK_CANONICALIZED),
    )
    conn.commit()


class TestDirectEmit:
    def test_canonicalized_emit_payload_shape(self, conn):
        ev_id = emit_symlink_canonicalized(
            conn=conn,
            claim_id=42,
            project="yoke",
            symlink_path="CLAUDE.md",
            canonical_path="AGENTS.md",
            symlink_target_id=252,
            canonical_target_id=251,
            item_id=1659,
        )
        assert ev_id  # event id returned on success
        p = _placeholder(conn)
        rows = conn.execute(
            "SELECT event_name, severity, envelope FROM events "
            f"WHERE event_id = {p}", (ev_id,),
        ).fetchall()
        assert len(rows) == 1
        name, severity, envelope = rows[0]
        assert name == "PathTargetSymlinkCanonicalized"
        assert severity == "INFO"
        assert '"claim_id": 42' in envelope
        assert '"canonical_path_string": "AGENTS.md"' in envelope
        assert '"symlink_target_id": 252' in envelope

    def test_skipped_emit_payload_shape(self, conn):
        ev_id = emit_symlink_skipped(
            conn=conn,
            claim_id=42,
            project="yoke",
            symlink_path="dangling.md",
            reason="dangling_target",
            target_attempt="missing/target.md",
            symlink_target_id=999,
            item_id=1659,
        )
        assert ev_id
        p = _placeholder(conn)
        rows = conn.execute(
            "SELECT event_name, severity, envelope FROM events "
            f"WHERE event_id = {p}", (ev_id,),
        ).fetchall()
        name, severity, envelope = rows[0]
        assert name == "PathTargetSymlinkSkipped"
        assert severity == "INFO"
        assert '"reason": "dangling_target"' in envelope
        assert '"target_attempt": "missing/target.md"' in envelope


class TestRegistrationEmits:
    def test_register_for_item_emits_canonicalized_with_claim_id(
        self, conn,
    ):
        from yoke_core.domain.path_claims_register import register_for_item

        _seed_project_row(conn, project_id=1, repo_path="/not/read/by/api")
        _seed_item(conn, item_id=1659, project="yoke")
        _seed_symlink_fact(conn)
        actor_id = local_human(conn)

        claim_id = register_for_item(
            conn,
            item_id=1659,
            integration_target="main",
            paths=["CLAUDE.md"],
            actor_id=actor_id,
            allow_planned=True,
        )
        assert isinstance(claim_id, int) and claim_id > 0
        rows = conn.execute(
            "SELECT event_name, envelope FROM events "
            "WHERE event_name = 'PathTargetSymlinkCanonicalized'",
        ).fetchall()
        assert len(rows) == 1, (
            "registration must emit one canonicalized event for CLAUDE.md"
        )
        envelope = rows[0][1]
        assert f'"claim_id": {claim_id}' in envelope
        assert '"symlink_path_string": "CLAUDE.md"' in envelope
        assert '"canonical_path_string": "AGENTS.md"' in envelope

    def test_register_for_item_covers_both_target_ids(
        self, conn,
    ):
        """A claim declaring only CLAUDE.md covers both target ids."""
        from yoke_core.domain.path_claims_register import register_for_item

        _seed_project_row(conn, project_id=1, repo_path="/not/read/by/api")
        _seed_item(conn, item_id=1659, project="yoke")
        _seed_symlink_fact(conn)
        actor_id = local_human(conn)

        claim_id = register_for_item(
            conn,
            item_id=1659,
            integration_target="main",
            paths=["CLAUDE.md"],
            actor_id=actor_id,
            allow_planned=True,
        )
        rows = conn.execute(
            "SELECT t.path_string FROM path_claim_targets pct "
            "JOIN path_targets t ON t.id = pct.target_id "
            f"WHERE pct.claim_id = {_placeholder(conn)} ORDER BY t.path_string",
            (claim_id,),
        ).fetchall()
        paths = sorted(str(r[0]) for r in rows)
        assert paths == ["AGENTS.md", "CLAUDE.md"]

    def test_cross_claim_symlink_overlap_classified_incompatible(
        self, conn,
    ):
        """Claim A declares CLAUDE.md, claim B declares AGENTS.md.

        Registration-time symlink expansion makes claim A cover both
        target ids, so the classifier sees the AGENTS.md collision.
        """
        from yoke_core.domain.path_claims_overlap import (
            OverlapClassification,
            classify_overlap,
        )
        from yoke_core.domain.path_claims_register import register_for_item

        _seed_project_row(conn, project_id=1, repo_path="/not/read/by/api")
        _seed_item(conn, item_id=1646, project="yoke")
        _seed_item(conn, item_id=1642, project="yoke")
        _seed_symlink_fact(conn)
        actor_id = local_human(conn)

        # Claim A: declares only CLAUDE.md. Registration auto-pairs with
        # AGENTS.md target_id so the claim covers both.
        register_for_item(
            conn,
            item_id=1646,
            integration_target="main",
            paths=["CLAUDE.md"],
            actor_id=actor_id,
            allow_planned=True,
        )

        # Resolve AGENTS.md target_id and ask the classifier what would
        # happen if claim B tried to register against it.
        row = conn.execute(
            "SELECT id FROM path_targets WHERE path_string='AGENTS.md'"
        ).fetchone()
        assert row is not None
        agents_target_id = int(row[0])

        verdict = classify_overlap(
            conn,
            target_ids=[agents_target_id],
            integration_target="main",
            phase="register",
            candidate_item_id=1642,
        )
        assert verdict == OverlapClassification.INCOMPATIBLE

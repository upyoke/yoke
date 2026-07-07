"""Coverage for project-relative path → ``path_targets.id`` resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    seed_target,
)
from yoke_core.domain.path_claims_resolve import (
    EmptyPathSet,
    NonProjectRelativePaths,
    SYMLINK_CANONICALIZED,
    SYMLINK_DANGLING_TARGET,
    SYMLINK_EXTERNAL_TARGET,
    UnknownPathTargets,
    _normalize_paths,
    expand_symlinks_from_snapshot_facts,
    expand_symlinks_to_canonical,
    resolve_or_plan_paths_to_target_ids,
    resolve_paths_to_target_ids,
)


@pytest.fixture
def project_tree(tmp_path: Path) -> Path:
    """Create a tmp project with a symlinked-rule-doc shape.

    Layout::

        <root>/
          AGENTS.md         (real file)
          CLAUDE.md         -> AGENTS.md
          notes/
            external_outside.txt  -> ../../outside.txt   (escapes root)
          dangling.md        -> missing/target.md         (target absent)
    """
    (tmp_path / "AGENTS.md").write_text("agents doctrine")
    os.symlink("AGENTS.md", tmp_path / "CLAUDE.md")
    notes = tmp_path / "notes"
    notes.mkdir()
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside")
    os.symlink(str(outside), notes / "external_outside.txt")
    os.symlink("missing/target.md", tmp_path / "dangling.md")
    return tmp_path


def _seed_snapshot(conn, *, sha: str) -> int:
    row = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (1, %s, '2026-05-01T00:00:00Z') RETURNING id",
        (sha,),
    ).fetchone()
    conn.commit()
    return int(row[0])


def _seed_snapshot_fact(
    conn,
    *,
    symlink_path: str,
    reason: str,
    target_attempt: str,
    canonical_path: str | None = None,
    symlink_target_id: int | None = None,
    canonical_target_id: int | None = None,
    sha: str = "sha-symlink",
) -> int:
    snapshot_id = _seed_snapshot(conn, sha=sha)
    conn.execute(
        "INSERT INTO path_snapshot_symlink_facts "
        "(snapshot_id, symlink_path, symlink_target_id, reason, "
        "target_attempt, canonical_path, canonical_target_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            snapshot_id,
            symlink_path,
            symlink_target_id,
            reason,
            target_attempt,
            canonical_path,
            canonical_target_id,
        ),
    )
    conn.commit()
    return snapshot_id


class TestResolve:
    def test_resolves_known_paths_in_operator_order(self, conn):
        a = seed_target(conn, path_string="runtime/api/domain")
        b = seed_target(conn, path_string="runtime/api/domain/render_body.py")
        ids = resolve_paths_to_target_ids(
            conn,
            "yoke",
            ["runtime/api/domain/render_body.py", "runtime/api/domain"],
        )
        assert ids == [b, a]

    def test_dedupes_paths_preserving_first_occurrence(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        ids = resolve_paths_to_target_ids(
            conn,
            "yoke",
            ["runtime/api/domain", "runtime/api/domain"],
        )
        assert ids == [target]

    def test_strips_whitespace_and_drops_empty_paths(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        ids = resolve_paths_to_target_ids(
            conn,
            "yoke",
            ["  runtime/api/domain  ", "", "  "],
        )
        assert ids == [target]

    def test_empty_input_raises_empty_path_set(self, conn):
        with pytest.raises(EmptyPathSet):
            resolve_paths_to_target_ids(conn, "yoke", [])

    def test_all_whitespace_input_raises_empty_path_set(self, conn):
        with pytest.raises(EmptyPathSet):
            resolve_paths_to_target_ids(conn, "yoke", [" ", ""])

    def test_unknown_path_lists_offenders(self, conn):
        seed_target(conn, path_string="runtime/api/domain")
        with pytest.raises(UnknownPathTargets) as excinfo:
            resolve_paths_to_target_ids(
                conn,
                "yoke",
                ["runtime/api/domain", "no/such/path", "also/missing"],
            )
        assert excinfo.value.project_id == 1
        assert excinfo.value.missing == ["no/such/path", "also/missing"]
        # Operator gets a single rejection surface listing both paths verbatim
        message = str(excinfo.value)
        assert "no/such/path" in message
        assert "also/missing" in message
        assert "project 1" in message

    def test_absolute_path_rejected_as_outside_repo(self, conn):
        with pytest.raises(NonProjectRelativePaths) as excinfo:
            resolve_paths_to_target_ids(conn, "yoke", ["/tmp/spec.txt"])
        assert excinfo.value.paths == ["/tmp/spec.txt"]

    def test_allow_planned_rejects_absolute_path(self, conn):
        with pytest.raises(NonProjectRelativePaths):
            resolve_or_plan_paths_to_target_ids(
                conn,
                "yoke",
                ["/tmp/spec.txt"],
                item_id=1585,
            )

    def test_resolves_canonical_symlink_from_snapshot_fact(self, conn):
        symlink = seed_target(conn, path_string="CLAUDE.md")
        canonical = seed_target(conn, path_string="AGENTS.md")
        _seed_snapshot_fact(
            conn,
            symlink_path="CLAUDE.md",
            symlink_target_id=symlink,
            reason=SYMLINK_CANONICALIZED,
            target_attempt="AGENTS.md",
            canonical_path="AGENTS.md",
            canonical_target_id=canonical,
        )
        ids = resolve_paths_to_target_ids(conn, "yoke", ["CLAUDE.md"])
        assert ids == [symlink, canonical]

    def test_skipped_symlink_fact_stays_name_only(self, conn):
        symlink = seed_target(conn, path_string="notes/external.txt")
        _seed_snapshot_fact(
            conn,
            symlink_path="notes/external.txt",
            symlink_target_id=symlink,
            reason=SYMLINK_EXTERNAL_TARGET,
            target_attempt="../outside.txt",
        )
        ids = resolve_paths_to_target_ids(
            conn, "yoke", ["notes/external.txt"],
        )
        assert ids == [symlink]

    def test_older_symlink_fact_not_used_after_newer_snapshot(self, conn):
        symlink = seed_target(conn, path_string="CLAUDE.md")
        canonical = seed_target(conn, path_string="AGENTS.md")
        _seed_snapshot_fact(
            conn,
            symlink_path="CLAUDE.md",
            symlink_target_id=symlink,
            reason=SYMLINK_CANONICALIZED,
            target_attempt="AGENTS.md",
            canonical_path="AGENTS.md",
            canonical_target_id=canonical,
            sha="sha-old",
        )
        _seed_snapshot(conn, sha="sha-new")
        ids = resolve_paths_to_target_ids(conn, "yoke", ["CLAUDE.md"])
        assert ids == [symlink]


class TestSymlinkExpansion:
    def test_snapshot_fact_expansion_returns_decision(self, conn):
        _seed_snapshot_fact(
            conn,
            symlink_path="CLAUDE.md",
            reason=SYMLINK_CANONICALIZED,
            target_attempt="AGENTS.md",
            canonical_path="AGENTS.md",
        )
        expanded, decisions = expand_symlinks_from_snapshot_facts(
            conn, "yoke", ["CLAUDE.md"],
        )
        assert expanded == ["CLAUDE.md", "AGENTS.md"]
        assert len(decisions) == 1
        assert decisions[0].target_attempt == "AGENTS.md"

    def test_in_repo_symlink_paired_with_canonical(self, project_tree: Path):
        expanded, decisions = expand_symlinks_to_canonical(
            ["CLAUDE.md"], project_root=project_tree,
        )
        assert expanded == ["CLAUDE.md", "AGENTS.md"]
        assert len(decisions) == 1
        d = decisions[0]
        assert d.symlink_path == "CLAUDE.md"
        assert d.canonical_path == "AGENTS.md"
        assert d.reason == SYMLINK_CANONICALIZED

    def test_external_target_emits_skip_no_canonical(self, project_tree: Path):
        expanded, decisions = expand_symlinks_to_canonical(
            ["notes/external_outside.txt"], project_root=project_tree,
        )
        assert expanded == ["notes/external_outside.txt"]
        assert len(decisions) == 1
        assert decisions[0].canonical_path is None
        assert decisions[0].reason == SYMLINK_EXTERNAL_TARGET

    def test_dangling_target_emits_skip(self, project_tree: Path):
        expanded, decisions = expand_symlinks_to_canonical(
            ["dangling.md"], project_root=project_tree,
        )
        assert expanded == ["dangling.md"]
        assert len(decisions) == 1
        assert decisions[0].reason == SYMLINK_DANGLING_TARGET
        assert decisions[0].canonical_path is None

    def test_non_symlink_path_no_decision(self, project_tree: Path):
        expanded, decisions = expand_symlinks_to_canonical(
            ["AGENTS.md"], project_root=project_tree,
        )
        assert expanded == ["AGENTS.md"]
        assert decisions == []

    def test_idempotency_when_both_names_already_present(self, project_tree: Path):
        expanded, decisions = expand_symlinks_to_canonical(
            ["CLAUDE.md", "AGENTS.md"], project_root=project_tree,
        )
        assert expanded == ["CLAUDE.md", "AGENTS.md"]
        # Decision is still emitted so events can record the canonicalization,
        # but no duplicate path is inserted.
        assert len(decisions) == 1
        assert decisions[0].reason == SYMLINK_CANONICALIZED

    def test_order_preserves_symlink_then_canonical(self, project_tree: Path):
        # Add a non-symlink before the symlink to confirm interleaving.
        (project_tree / "z.md").write_text("real")
        expanded, _ = expand_symlinks_to_canonical(
            ["z.md", "CLAUDE.md"], project_root=project_tree,
        )
        assert expanded == ["z.md", "CLAUDE.md", "AGENTS.md"]

    def test_normalize_paths_unchanged_by_helper_install(self):
        # Existing _normalize_paths semantics are byte-for-byte
        # identical with or without the symlink helper installed.
        raw = ["  a.md  ", "", "b.md", "a.md", "  "]
        assert _normalize_paths(raw) == ["a.md", "b.md"]

"""Whole-snapshot retention preserving identity sightings and live consumers."""

from yoke_core.domain.retention_table_policies import Cleanup


def snapshot_policy():
    where = """
    t.id <> (SELECT MAX(s.id) FROM path_snapshots s WHERE s.project_id=t.project_id)
    AND t.id <> COALESCE((
        SELECT MAX(s.id) FROM path_snapshots s WHERE s.project_id=t.project_id
        AND EXISTS (SELECT 1 FROM path_snapshot_entries e JOIN path_targets p
                    ON p.id=e.target_id WHERE e.snapshot_id=s.id AND p.kind='file')
    ), -1)
    AND NOT EXISTS (
        SELECT 1 FROM path_snapshot_entries e JOIN path_targets p ON p.id=e.target_id
        WHERE e.snapshot_id=t.id AND p.generation=(
            SELECT MAX(g.generation) FROM path_targets g
            WHERE g.project_id=p.project_id AND g.path_string=p.path_string
        ) AND t.id=(SELECT MAX(sighting.snapshot_id) FROM path_snapshot_entries sighting
                    WHERE sighting.target_id=p.id)
    )
    AND NOT EXISTS (
        SELECT 1 FROM item_worktrees w JOIN items i ON i.id=w.item_id
        WHERE w.state='active' AND i.project_id=t.project_id AND w.commit_sha=t.commit_sha
    )
    AND NOT EXISTS (
        SELECT 1 FROM path_integrity_runs r WHERE r.project_id=t.project_id
        AND r.commit_sha=t.commit_sha AND (r.status='running' OR EXISTS (
            SELECT 1 FROM path_integrity_failures f WHERE f.run_id=r.id AND f.repair_status='open'
        ))
    )
    AND NOT EXISTS (
        SELECT 1 FROM path_claims c JOIN path_claim_targets ct ON ct.claim_id=c.id
        JOIN path_targets p ON p.id=ct.target_id
        WHERE c.state IN ('planned','blocked','active') AND p.project_id=t.project_id
        AND c.base_commit_sha=t.commit_sha
    )
    """
    return Cleanup(
        "path_snapshots",
        ("id",),
        where,
        children=(
            ("path_snapshot_entries", "snapshot_id", "id"),
            ("path_snapshot_symlink_facts", "snapshot_id", "id"),
        ),
        locks=(
            "path_targets",
            "item_worktrees",
            "items",
            "path_integrity_runs",
            "path_integrity_failures",
            "path_claims",
            "path_claim_targets",
        ),
        reason="latest/content snapshots, last sightings, active heads, claims and integrity references stay whole",
    )

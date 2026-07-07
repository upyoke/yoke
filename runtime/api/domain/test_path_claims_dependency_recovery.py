"""Coverage for the data-driven recovery sweep over released claims.

The terminal-hook fix in ``path_claims_item_hook_release`` closes the
forward path so future item-terminal releases also propagate. This
sibling helper, ``unblock_stranded_for_released``, is the recovery
surface for downstreams that were stranded *before* the fix landed —
items whose upstream was released via the old hook path with no
propagation. The CLI wrapper (``path-claim-unblock-stranded``)
exposes it through the service-client registry.
"""

from __future__ import annotations

import json

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims_dependency_propagation import (
    unblock_stranded_for_released,
)


def _seed_item(conn, *, item_id: int, status: str = "implementing") -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', %s, 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, status, item_id),
    )
    conn.commit()
    return item_id


def _seed_claim(
    conn, *, item_id, target_id, state, blocked_reason=None,
):
    actor = local_human(conn)
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, "
        "registered_at, blocked_reason) "
        "VALUES (%s, 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', %s) RETURNING id",
        (state, actor, item_id, blocked_reason),
    )
    cid = int(cur.fetchone()[0])
    if state == "active":
        conn.execute(
            "UPDATE path_claims SET activated_at = '2026-05-01T01:00:00Z', "
            "base_commit_sha = %s WHERE id = %s", (SNAP, cid),
        )
    elif state == "released":
        conn.execute(
            "UPDATE path_claims SET released_at = '2026-05-01T02:00:00Z', "
            "release_reason = 'test' WHERE id = %s", (cid,),
        )
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


def _seed_pair(conn, *, item_id, path):
    """Released upstream + blocked downstream sharing one path target."""
    target = seed_target(conn, path_string=path)
    upstream_item = _seed_item(conn, item_id=item_id)
    downstream_item = _seed_item(conn, item_id=item_id + 1)
    upstream = _seed_claim(
        conn, item_id=upstream_item, target_id=target, state="released",
    )
    downstream = _seed_claim(
        conn, item_id=downstream_item, target_id=target, state="blocked",
        blocked_reason=f"serial-via-dependency on path_claims.id={upstream}",
    )
    return upstream, downstream


class TestSweepEveryReleasedUpstream:
    def test_sweep_unblocks_stranded_downstream(self, conn):
        """AC-7: omitting --claim-id walks every released upstream."""
        upstream_a, downstream_a = _seed_pair(
            conn, item_id=20001, path="runtime/api/domain",
        )
        upstream_b, downstream_b = _seed_pair(
            conn, item_id=20003, path="docs",
        )

        flipped = unblock_stranded_for_released(conn)

        assert downstream_a in flipped
        assert downstream_b in flipped
        states = dict(
            conn.execute(
                "SELECT id, state FROM path_claims WHERE id IN (%s, %s)",
                (downstream_a, downstream_b),
            ).fetchall()
        )
        assert states[downstream_a] == "planned"
        assert states[downstream_b] == "planned"


class TestSingleClaimFilter:
    def test_single_claim_id_targets_one_upstream(self, conn):
        """AC-7: --claim-id propagates only the named upstream."""
        upstream_a, downstream_a = _seed_pair(
            conn, item_id=20101, path="runtime/api/domain",
        )
        _, downstream_b = _seed_pair(conn, item_id=20103, path="docs")

        flipped = unblock_stranded_for_released(conn, claim_id=upstream_a)

        assert flipped == [downstream_a]
        states = dict(
            conn.execute(
                "SELECT id, state FROM path_claims WHERE id IN (%s, %s)",
                (downstream_a, downstream_b),
            ).fetchall()
        )
        assert states[downstream_a] == "planned"
        assert states[downstream_b] == "blocked"

    def test_yok1594_shape_unblocks_after_released_upstream(self, conn):
        """Regression: claim 33 blocked by claim 21."""
        target = seed_target(
            conn,
            path_string="runtime/api/domain/idea_readiness_check.py",
        )
        upstream_item = _seed_item(conn, item_id=1585, status="done")
        downstream_item = _seed_item(conn, item_id=1594, status="refined-idea")
        upstream = _seed_claim(
            conn, item_id=upstream_item, target_id=target, state="released",
        )
        downstream = _seed_claim(
            conn, item_id=downstream_item, target_id=target, state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={upstream}",
        )

        flipped = unblock_stranded_for_released(conn, claim_id=upstream)

        assert flipped == [downstream]
        row = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (downstream,),
        ).fetchone()
        assert row["state"] == "planned"
        assert row["blocked_reason"] is None

    def test_single_claim_id_skips_non_released_upstream(self, conn):
        """Single-claim recovery only propagates released upstream claims."""
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream_item = _seed_item(conn, item_id=20105)
        downstream_item = _seed_item(conn, item_id=20106)
        upstream = _seed_claim(
            conn, item_id=upstream_item, target_id=target, state="planned",
        )
        downstream = _seed_claim(
            conn, item_id=downstream_item, target_id=target, state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={upstream}",
        )

        flipped = unblock_stranded_for_released(conn, claim_id=upstream)

        assert flipped == []
        row = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (downstream,),
        ).fetchone()
        assert row["state"] == "blocked"
        assert row["blocked_reason"] is not None


class TestIdempotence:
    def test_second_sweep_is_a_noop(self, conn):
        """AC-8: a second sweep produces no further flips."""
        _seed_pair(conn, item_id=20201, path="runtime/api/domain")

        first = unblock_stranded_for_released(conn)
        second = unblock_stranded_for_released(conn)

        assert len(first) == 1
        assert second == []

    def test_sweep_skips_terminal_downstream(self, conn):
        """AC-8: planned/cancelled downstreams are never reflipped."""
        target_a = seed_target(conn, path_string="runtime/api/domain")
        target_b = seed_target(conn, path_string="docs")
        upstream_item = _seed_item(conn, item_id=20301)
        planned_item = _seed_item(conn, item_id=20302)
        cancelled_item = _seed_item(conn, item_id=20303)
        upstream = _seed_claim(
            conn, item_id=upstream_item, target_id=target_a,
            state="released",
        )
        # Already-planned downstream that happens to share a target.
        _seed_claim(
            conn, item_id=planned_item, target_id=target_a, state="planned",
        )
        # Cancelled downstream with stale blocked_reason — must not be
        # resurrected from cancelled to planned.
        cur = conn.execute(
            "INSERT INTO path_claims "
            "(state, mode, actor_id, item_id, integration_target, "
            "registered_at, blocked_reason, cancelled_at, cancel_reason) "
            "VALUES ('cancelled', 'exclusive', %s, %s, 'main', "
            "'2026-05-01T00:00:00Z', %s, '2026-05-01T03:00:00Z', "
            "'abandoned') RETURNING id",
            (
                local_human(conn), cancelled_item,
                f"serial-via-dependency on path_claims.id={upstream}",
            ),
        )
        cancelled_claim = int(cur.fetchone()[0])
        conn.execute(
            "INSERT INTO path_claim_targets "
            "(claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (cancelled_claim, target_b),
        )
        conn.commit()

        flipped = unblock_stranded_for_released(conn)

        assert flipped == []
        assert (
            conn.execute(
                "SELECT state FROM path_claims WHERE id = %s",
                (cancelled_claim,),
            ).fetchone()["state"]
            == "cancelled"
        )


class _ConnProxy:
    """Wrap an in-memory connection so the CLI wrapper's ``close()``
    call is a no-op — pytest's ``conn`` fixture owns the lifecycle."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):  # noqa: D401 — close is a no-op for tests
        return None

    def __getattr__(self, name):
        return getattr(self._conn, name)


class TestServiceClientCli:
    def test_cli_emits_flipped_payload(self, conn, capsys, monkeypatch):
        """The CLI wrapper invokes the helper and emits a JSON payload."""
        from yoke_core.api import service_client_path_claims as scpc

        _, downstream = _seed_pair(
            conn, item_id=20401, path="runtime/api/domain",
        )
        monkeypatch.setattr(scpc, "open_conn", lambda: _ConnProxy(conn))

        rc = scpc.cmd_path_claim_unblock_stranded([])
        assert rc == 0

        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["success"] is True
        assert payload["flipped_count"] == 1
        assert downstream in payload["flipped_claim_ids"]
        assert "path-claim-unblock-stranded" in scpc.PATH_CLAIMS_COMMANDS

    def test_cli_filters_to_single_claim(self, conn, capsys, monkeypatch):
        """AC-7: --claim-id flag scopes the sweep to one upstream."""
        from yoke_core.api import service_client_path_claims as scpc

        upstream_a, downstream_a = _seed_pair(
            conn, item_id=20501, path="runtime/api/domain",
        )
        _, downstream_b = _seed_pair(conn, item_id=20503, path="docs")

        monkeypatch.setattr(scpc, "open_conn", lambda: _ConnProxy(conn))

        rc = scpc.cmd_path_claim_unblock_stranded(
            ["--claim-id", str(upstream_a)],
        )
        assert rc == 0

        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["flipped_count"] == 1
        assert downstream_a in payload["flipped_claim_ids"]
        assert downstream_b not in payload["flipped_claim_ids"]

    def test_cli_help_returns_zero(self, capsys):
        """The service-client help path should be a successful query."""
        from yoke_core.api import service_client_path_claims as scpc

        rc = scpc.cmd_path_claim_unblock_stranded(["--help"])

        assert rc == 0
        assert "path-claim-unblock-stranded" in capsys.readouterr().out

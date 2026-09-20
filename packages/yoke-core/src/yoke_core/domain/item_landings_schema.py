"""The append-only record of every landing an item has made.

An item's own columns hold one landing — the newest — and the next landing
overwrites them, so a branch that landed twice is indistinguishable from one
that landed once and no landing can be audited after the fact. This table is
where each landing stays.

The row is keyed on ``merge_sha``: the merge commit is what delivery is
actually asked about, because carried-work ranges and release-candidate
ancestry are both commit-based, while a pull request number is a provider
label and a landing time is a time. A fast-forward or squash that leaves no
distinct merge commit records the landed commit as its ``merge_sha`` and says
so in ``route``, so a row is never keyless.

``candidate_sha`` rides beside it rather than collapsing into it. They differ:
the candidate is the lane commit the item's verification covered, and a
landing recorded before its merge commit was resolvable has only that.

``id`` is monotonic, and it — not ``landed_at`` — is the tiebreaker for
"which landing is the newest". Two landings can share a timestamp, and an
item that landed four times in one day is the case this table exists for.

``origin`` says how the row got here. Close-out writes ``recorded``. A
git-history backfill writes ``reconstructed``, whose ``landed_at`` is the
merge commit's committer time and can run minutes early of the GitHub
observed moment for a merge-queue landing.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script

#: The merge queue merged this landing on GitHub.
ROUTE_MERGE_QUEUE = "merge_queue"
#: The standalone merge engine created a merge commit on the base branch.
ROUTE_STANDALONE = "standalone"
#: The branch reached the base with no merge commit of its own, so the
#: landed commit is the landing identity.
ROUTE_FAST_FORWARD = "fast_forward"

#: Every route a landing may be recorded under.
LANDING_ROUTES = (ROUTE_MERGE_QUEUE, ROUTE_STANDALONE, ROUTE_FAST_FORWARD)

#: Close-out observed this landing as it happened.
ORIGIN_RECORDED = "recorded"
#: The row was rebuilt from git; ``landed_at`` is committer time.
ORIGIN_RECONSTRUCTED = "reconstructed"

#: Every origin a landing may be stored under.
LANDING_ORIGINS = (ORIGIN_RECORDED, ORIGIN_RECONSTRUCTED)

_ROUTE_SQL = ",".join(f"'{route}'" for route in LANDING_ROUTES)
_ORIGIN_SQL = ",".join(f"'{origin}'" for origin in LANDING_ORIGINS)

ITEM_LANDINGS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS item_landings (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id),
  merge_sha TEXT NOT NULL,
  candidate_sha TEXT NOT NULL DEFAULT '',
  pr_number TEXT NOT NULL DEFAULT '',
  target_branch TEXT NOT NULL DEFAULT '',
  route TEXT NOT NULL CHECK(route IN ({_ROUTE_SQL})),
  landed_at TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT '{ORIGIN_RECORDED}'
    CHECK(origin IN ({_ORIGIN_SQL})),
  UNIQUE(item_id, merge_sha)
);
CREATE INDEX IF NOT EXISTS idx_item_landings_item
  ON item_landings(item_id, id);
"""


def ensure_item_landings_schema(conn: Any) -> None:
    """Converge the additive item-landings table and origin column on ``conn``."""
    execute_schema_script(conn, ITEM_LANDINGS_CREATE_SQL)
    _add_column_if_not_exists(
        conn,
        "item_landings",
        "origin",
        f"TEXT NOT NULL DEFAULT '{ORIGIN_RECORDED}'",
    )


__all__ = [
    "ITEM_LANDINGS_CREATE_SQL",
    "LANDING_ORIGINS",
    "LANDING_ROUTES",
    "ORIGIN_RECONSTRUCTED",
    "ORIGIN_RECORDED",
    "ROUTE_FAST_FORWARD",
    "ROUTE_MERGE_QUEUE",
    "ROUTE_STANDALONE",
    "ensure_item_landings_schema",
]

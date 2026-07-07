"""Actor-identity and path-claim table DDL.

Owns the five tables that move coordination truth from item/task-level
``work_claims`` toward actor- and path-aware claims while preserving the
current delivery family. The DDL itself is the only authoritative source
for fresh installs and the one-shot conversion migration alike, mirroring
the precedent set by :mod:`schema_init_path_integrity_tables`.

Tables created (idempotent):

* ``actors`` — durable accountable-subject table. Carries ``kind``
  (``'human'`` or ``'system'``) and ``system_component`` (required-and-
  unique for system actors, NULL for humans). Profile fields do not live
  on this table; future User/profile identity attaches to ``actors.id``
  in a later extension.
* ``actor_labels`` — surface-specific human-readable label projection.
  Renders ``actors.id`` to surface labels. ``surface='display'`` is the
  generic actor-facing display projection; ``surface='github_label'`` is
  the GitHub sync projection. Two uniqueness constraints together ensure
  that for any given surface, every actor has at most one label AND every
  label maps to at most one actor — these guarantee the central rendering
  helper in :mod:`yoke_core.domain.actors` cannot produce ambiguous
  output.
* ``path_claims`` — first path-claim storage. One row per registered
  intent to edit a declared path coverage on an integration target.
  Carries explicit typed ownership (``owner_kind`` in
  ``('item','session','process')`` plus the matching one of
  ``owner_item_id`` / ``owner_session_id`` / ``owner_work_claim_id``)
  and provenance (``registered_by_actor_id`` plus optional
  ``registered_by_session_id``) separately so the registering session
  cannot be mistaken for the path holder. The legacy ``actor_id`` /
  ``session_id`` / ``item_id`` / ``work_claim_id`` columns remain
  populated alongside the typed columns during cutover for backwards
  compatibility; new readers MUST prefer the typed owner fields.
  Lifecycle states: ``planned`` (declared, no edit permission),
  ``blocked`` (planned but serially gated behind another claim),
  ``active`` (door-lock acquired), ``released`` (work landed or scope
  ended), ``cancelled`` (lineage abandoned). Modes: ``exclusive`` (the
  only mode the validator currently accepts); ``parallel`` exists in
  schema but the validator rejects it until it is explicitly unlocked.
* ``path_claim_targets`` — junction between a claim and the canonical
  path targets it declares coverage over. References ``path_targets`` by
  id (the registry the verifier already owns).
* ``path_claim_amendments`` — append-only amendment history for a claim.
  Stores the amendment kind and a JSON payload describing what changed,
  so future revalidation/override layers have the trail they need.
* ``path_claim_overrides`` — operator-collision approvals. One row per
  invoked override permitting ``path_claim_id`` to proceed past
  ``blocking_claim_id`` for the anchor targets in
  ``blocking_path_targets`` (JSON int array). State consumed by
  :func:`yoke_core.domain.path_claims_override.is_active_override`;
  the ``PathClaimOverride`` event is telemetry alongside the row.

Schema layering rules:

* Tables are additive. They reference ``path_targets`` and
  ``path_snapshots`` by id, ``actors`` by id, and ``harness_sessions`` by
  ``session_id``. No FK-cycle exists.
* The lifecycle CHECK constraints encode the registration/activation
  state machine; domain code treats the CHECK as the definitive set.
  Adding a new state requires updating the CHECK and the domain
  validator together.
* The two ``actor_labels`` uniqueness constraints — ``UNIQUE(surface,
  label)`` and ``UNIQUE(actor_id, surface)`` — together prevent two
  actors from claiming the same external label on the same surface AND
  prevent one actor from carrying multiple labels on the same surface.
  The central rendering helper relies on both.
* The partial unique index on ``actors.system_component`` (``WHERE
  system_component IS NOT NULL``) preserves uniqueness for system rows
  without forcing humans to disambiguate against each other on a NULL
  column.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


_REQUIRED_TABLES = (
    "actors",
    "actor_labels",
    "path_claims",
    "path_claim_targets",
    "path_claim_amendments",
    "path_claim_overrides",
)

_ACTOR_IDENTITY_SQL = """
        CREATE TABLE IF NOT EXISTS actors (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('human','system')),
            system_component TEXT,
            created_at TEXT NOT NULL,
            CHECK (
                (kind = 'system' AND system_component IS NOT NULL)
                OR
                (kind = 'human' AND system_component IS NULL)
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_actors_system_component
            ON actors(system_component)
            WHERE system_component IS NOT NULL;

        CREATE TABLE IF NOT EXISTS actor_labels (
            id INTEGER PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            surface TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(surface, label),
            UNIQUE(actor_id, surface)
        );
        CREATE INDEX IF NOT EXISTS idx_actor_labels_actor
            ON actor_labels(actor_id);
"""


def create_actor_identity_tables(conn: Any) -> None:
    """Create durable actor identity tables and indexes (idempotent)."""
    execute_schema_script(conn, _ACTOR_IDENTITY_SQL)
    conn.commit()


def create_actor_path_claim_tables(conn: Any) -> None:
    """Create the actor and path-claim tables and indexes (idempotent)."""
    create_actor_identity_tables(conn)
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS path_claims (
            id INTEGER PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'planned'
                CHECK(state IN (
                    'planned','blocked','active','released','cancelled'
                )),
            mode TEXT NOT NULL DEFAULT 'exclusive'
                CHECK(mode IN ('exclusive','parallel','exception')),
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            session_id TEXT REFERENCES harness_sessions(session_id),
            item_id INTEGER,
            work_claim_id INTEGER REFERENCES work_claims(id),
            owner_kind TEXT
                CHECK(owner_kind IS NULL OR owner_kind IN (
                    'item','session','process'
                )),
            owner_item_id INTEGER,
            owner_session_id TEXT REFERENCES harness_sessions(session_id),
            owner_work_claim_id INTEGER REFERENCES work_claims(id),
            registered_by_actor_id INTEGER REFERENCES actors(id),
            registered_by_session_id TEXT
                REFERENCES harness_sessions(session_id),
            integration_target TEXT NOT NULL,
            base_commit_sha TEXT,
            registered_at TEXT NOT NULL,
            activated_at TEXT,
            released_at TEXT,
            cancelled_at TEXT,
            release_reason TEXT,
            cancel_reason TEXT,
            blocked_reason TEXT,
            exception_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_path_claims_state
            ON path_claims(state);
        CREATE INDEX IF NOT EXISTS idx_path_claims_actor
            ON path_claims(actor_id);
        CREATE INDEX IF NOT EXISTS idx_path_claims_session
            ON path_claims(session_id);
        CREATE INDEX IF NOT EXISTS idx_path_claims_item
            ON path_claims(item_id);
        CREATE INDEX IF NOT EXISTS idx_path_claims_work_claim
            ON path_claims(work_claim_id);
        CREATE INDEX IF NOT EXISTS idx_path_claims_owner_kind
            ON path_claims(owner_kind);
        CREATE INDEX IF NOT EXISTS idx_path_claims_owner_item
            ON path_claims(owner_item_id);
        CREATE INDEX IF NOT EXISTS idx_path_claims_owner_session
            ON path_claims(owner_session_id);
        CREATE INDEX IF NOT EXISTS idx_path_claims_owner_work_claim
            ON path_claims(owner_work_claim_id);
        CREATE INDEX IF NOT EXISTS idx_path_claims_integration_target
            ON path_claims(integration_target, state);

        CREATE TABLE IF NOT EXISTS path_claim_targets (
            id INTEGER PRIMARY KEY,
            claim_id INTEGER NOT NULL REFERENCES path_claims(id),
            target_id INTEGER NOT NULL REFERENCES path_targets(id),
            declared_at TEXT NOT NULL,
            UNIQUE(claim_id, target_id)
        );
        CREATE INDEX IF NOT EXISTS idx_path_claim_targets_target
            ON path_claim_targets(target_id);

        CREATE TABLE IF NOT EXISTS path_claim_amendments (
            id INTEGER PRIMARY KEY,
            claim_id INTEGER NOT NULL REFERENCES path_claims(id),
            amended_at TEXT NOT NULL,
            amendment_kind TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_path_claim_amendments_claim
            ON path_claim_amendments(claim_id);

        CREATE TABLE IF NOT EXISTS path_claim_overrides (
            id INTEGER PRIMARY KEY,
            path_claim_id INTEGER NOT NULL REFERENCES path_claims(id),
            blocking_claim_id INTEGER REFERENCES path_claims(id),
            blocking_path_targets TEXT NOT NULL DEFAULT '[]',
            override_point TEXT NOT NULL,
            conflict_reason TEXT,
            integration_target TEXT,
            actor_id INTEGER,
            actor_reason TEXT NOT NULL,
            item_id INTEGER,
            project TEXT,
            session_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_path_claim_overrides_pair
            ON path_claim_overrides(path_claim_id, blocking_claim_id);
    """)
    conn.commit()


def required_tables() -> tuple[str, ...]:
    """Return the tuple of table names this module owns.

    Consumed by the one-shot migration's ``invariants(conn)`` hook so the
    post-apply assertion list lives next to the DDL it asserts.
    """
    return _REQUIRED_TABLES


__all__ = [
    "create_actor_identity_tables",
    "create_actor_path_claim_tables",
    "required_tables",
]

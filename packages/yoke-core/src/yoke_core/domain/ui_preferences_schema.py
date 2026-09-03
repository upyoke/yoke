"""Schema DDL for per-actor UI preferences and Overview activation facts.

Owns two additive tables behind the workbench Overview's activation
modules:

* ``actor_ui_preferences`` — generic per-actor key/value preferences so
  later actor-scoped preferences (for example a time-zone override)
  share the surface. Overview module dismissals use
  ``pref_key = 'overview.module.dismissed.<module_key>'`` with value
  ``'1'``; ``UNIQUE(actor_id, pref_key)`` makes the upsert the whole
  write contract.
* ``overview_activation_facts`` — universe-scoped monotone activation
  latches, one row per activation module key. A row records that the
  module's signal was observed satisfied at least once; rows are never
  updated or deleted by product code, so a signal that later disappears
  (a deleted session, a dropped binding) cannot un-activate a module.
* ``overview_machine_activation_facts`` — the same monotone latch keyed
  per ``(machine_id, module_key)`` for the modules that answer for one
  machine rather than for the universe (machine connected, harness
  connected). A universe-level ``connect_harness`` row written before
  this table existed is inert: product code neither reads nor deletes it.

All three shapes are additive: the schema-init chain applies them
idempotently on every server boot, so every born universe converges on
next start. ``actor_ui_preferences`` FKs into ``actors``, so this module
runs after ``create_actor_identity_tables`` in the init chain.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


REQUIRED_UI_PREFERENCE_TABLES = (
    "actor_ui_preferences",
    "overview_activation_facts",
    "overview_machine_activation_facts",
)

ACTOR_UI_PREFERENCES_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS actor_ui_preferences (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER NOT NULL REFERENCES actors(id),
    pref_key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(actor_id, pref_key)
)
"""

OVERVIEW_ACTIVATION_FACTS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS overview_activation_facts (
    id INTEGER PRIMARY KEY,
    module_key TEXT NOT NULL UNIQUE,
    activated_at TEXT NOT NULL
)
"""

OVERVIEW_MACHINE_ACTIVATION_FACTS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS overview_machine_activation_facts (
    id INTEGER PRIMARY KEY,
    machine_id TEXT NOT NULL,
    module_key TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    UNIQUE(machine_id, module_key)
)
"""


def create_ui_preference_tables(conn: Any) -> None:
    """Create the UI preference and activation-fact tables, idempotently."""
    execute_schema_script(
        conn,
        ACTOR_UI_PREFERENCES_CREATE_SQL
        + ";"
        + OVERVIEW_ACTIVATION_FACTS_CREATE_SQL
        + ";"
        + OVERVIEW_MACHINE_ACTIVATION_FACTS_CREATE_SQL,
    )
    conn.commit()


def required_tables() -> tuple[str, ...]:
    return REQUIRED_UI_PREFERENCE_TABLES


__all__ = [
    "ACTOR_UI_PREFERENCES_CREATE_SQL",
    "OVERVIEW_ACTIVATION_FACTS_CREATE_SQL",
    "OVERVIEW_MACHINE_ACTIVATION_FACTS_CREATE_SQL",
    "REQUIRED_UI_PREFERENCE_TABLES",
    "create_ui_preference_tables",
    "required_tables",
]

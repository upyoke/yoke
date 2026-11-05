"""Definition-owned presentation in the session roster read model.

A roster row's level glyph comes from its project's effective levels: the
project's ``session-routing`` override, else the stored universe ``levels``
setting, else the shipped scheme. Observed model/effort facts determine its
level; a requested stamp cannot override them.
"""

import json

from runtime.api.domain.handlers.sessions_list_handler_test_support import (
    _insert_session as _base_insert_session,
    _iso,
)
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain.universe_levels import write_universe_levels


def _insert_session(conn, session_id, **kwargs):
    _base_insert_session(conn, session_id, **kwargs)
    conn.execute(
        "UPDATE harness_sessions SET model='gpt-6.1-sol',reasoning_effort='medium' WHERE session_id=%s",
        (session_id,),
    )
    conn.commit()


def _levels(name: str, glyph: str) -> list[dict]:
    return [
        {
            "name": name,
            "glyph": glyph,
            "options": [
                {
                    "model": "gpt-6.1-sol",
                    "min_effort": "medium",
                }
            ],
        }
    ]


def _set_project_override(conn, levels: list[dict]) -> None:
    conn.execute(
        "INSERT INTO project_capabilities "
        "(project_id,type,settings,created_at) VALUES (1,'session-routing',%s,%s) "
        "ON CONFLICT(project_id,type) DO UPDATE SET settings=EXCLUDED.settings",
        (json.dumps({"levels": levels}), _iso()),
    )
    conn.commit()


def _only_row():
    rows = list_sessions()
    assert len(rows) == 1
    return rows[0]


def test_definition_owned_level_and_executor_presentation(test_db) -> None:
    _set_project_override(test_db, _levels("RESEARCH", "🔬"))
    _insert_session(
        test_db,
        "s-presented",
        last_heartbeat=_iso(),
        executor="codex",
        level="RESEARCH",
    )

    row = _only_row()
    assert (row["level_label"], row["level_glyph"]) == ("RESEARCH", "🔬")
    assert (row["executor_mark"], row["executor_class_name"]) == (
        "X",
        "h-codex",
    )


def test_roster_reads_the_shipped_scheme_when_nothing_is_stored(test_db) -> None:
    _insert_session(test_db, "s-default", last_heartbeat=_iso(), level="SENIOR")

    row = _only_row()
    assert (row["level_label"], row["level_glyph"]) == ("SENIOR", "\U0001f989")


def test_roster_reads_the_stored_universe_levels(test_db) -> None:
    write_universe_levels(test_db, _levels("RESEARCH", "🔬"), actor_id=None)
    _insert_session(test_db, "s-universe", last_heartbeat=_iso(), level="RESEARCH")

    row = _only_row()
    assert (row["level_label"], row["level_glyph"]) == ("RESEARCH", "🔬")


def test_project_override_wins_over_the_universe_levels(test_db) -> None:
    write_universe_levels(test_db, _levels("RESEARCH", "🔬"), actor_id=None)
    _set_project_override(test_db, _levels("RESEARCH", "🚀"))
    _insert_session(test_db, "s-override", last_heartbeat=_iso(), level="RESEARCH")

    row = _only_row()
    assert (row["level_label"], row["level_glyph"]) == ("RESEARCH", "🚀")


def test_unknown_stamped_level_cannot_override_actual_model(test_db) -> None:
    _insert_session(test_db, "s-unknown", last_heartbeat=_iso(), level="DARIUS")

    row = _only_row()
    assert (row["level_label"], row["level_glyph"]) == ("SENIOR", "🦉")

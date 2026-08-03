"""Definition-owned presentation in the session roster read model."""

from runtime.api.domain.handlers.test_sessions_list_handler import (
    _insert_session,
    _iso,
)
from yoke_core.domain.sessions_list_read import list_sessions


def test_definition_owned_lane_and_executor_presentation(test_db) -> None:
    test_db.execute(
        "INSERT INTO project_capabilities "
        "(project_id,type,settings,created_at) VALUES (1,'session-routing',%s,%s) "
        "ON CONFLICT(project_id,type) DO UPDATE SET settings=EXCLUDED.settings",
        (
            '{"lane_metadata":{"RESEARCH":{"label":"Research","glyph":"🔬"}}}',
            _iso(),
        ),
    )
    test_db.commit()
    _insert_session(
        test_db,
        "s-presented",
        last_heartbeat=_iso(),
        executor="codex-app",
        lane="RESEARCH",
    )

    row = list_sessions()[0]
    assert (row["lane_label"], row["lane_glyph"]) == ("Research", "🔬")
    assert (row["executor_mark"], row["executor_class_name"]) == (
        "X",
        "h-codex",
    )

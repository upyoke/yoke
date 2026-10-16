"""Named board snapshot transport and rendering behavior."""

from __future__ import annotations

import json
import textwrap

import pytest

from yoke_contracts.board.config import parse_config
from yoke_contracts.board.art import ArtConfig, parse_art_config
from yoke_contracts.board.renderer import render_board_from_payload
from yoke_core.board.data import collect_board_data
from yoke_core.board.db import BoardDB
from yoke_core.board.renderer import render_board
from runtime.api.fixtures.file_test_db import connect_test_db


def _direct_render(
    db_path, scope, config_path, *, seed, repo_root=None, vision_entries=()
):
    return render_board(db_path, scope, config_path, seed=seed, repo_root=repo_root)


def _data_fed_render(
    db_path, scope, config_path, *, seed, repo_root=None, vision_entries=()
):
    """Collect and render through JSON with the same inputs."""
    config = parse_config(config_path, repo_root=repo_root)
    art_config = parse_art_config(config_path, repo_root=repo_root)
    with BoardDB(db_path) as db:
        payload = collect_board_data(
            db,
            scope=scope,
            config=config,
            repo_root=repo_root,
            vision_entries=vision_entries,
        )
    # Prove transport fidelity: everything survives a JSON round trip.
    payload = json.loads(json.dumps(payload))
    return render_board_from_payload(
        payload,
        scope=scope,
        config=config,
        art_config=art_config,
        seed=seed,
        repo_root=repo_root,
        vision_entries=list(vision_entries),
    )


def test_parity_populated_board(populated_db, config_file):
    direct = _direct_render(populated_db, "yoke", config_file, seed=42)
    fed = _data_fed_render(populated_db, "yoke", config_file, seed=42)
    assert fed == direct
    assert "First item" in fed


def test_parity_empty_board(test_db_path, config_file):
    direct = _direct_render(test_db_path, "yoke", config_file, seed=7)
    fed = _data_fed_render(test_db_path, "yoke", config_file, seed=7)
    assert fed == direct


def test_parity_velocity_meter_strategy_revisions(populated_db, tmp_path):
    """Saved strategy revisions feed the velocity series."""
    from datetime import date

    from runtime.api.board.tests.helpers import insert_doc_revision

    cfg = tmp_path / "config"
    cfg.write_text("dashboard_velocity_meter=true\n")
    today = date.today().isoformat()
    insert_doc_revision(
        populated_db,
        "yoke",
        "MISSION",
        1,
        10,
        f"{today}T09:00:00Z",
    )
    insert_doc_revision(
        populated_db,
        "yoke",
        "MISSION",
        2,
        3300,
        f"{today}T10:00:00Z",
    )
    direct = _direct_render(populated_db, "yoke", str(cfg), seed=42)
    fed = _data_fed_render(populated_db, "yoke", str(cfg), seed=42)
    assert fed == direct
    assert "120d strategy" in fed


def test_payload_uses_stamped_session_project_identity(populated_db, config_file):
    conn = connect_test_db(populated_db)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS harness_sessions (
                session_id TEXT PRIMARY KEY,
                executor TEXT NOT NULL,
                executor_surface TEXT DEFAULT NULL,
                provider TEXT,
                model TEXT,
                reasoning_effort TEXT DEFAULT NULL,
                context_window_tokens INTEGER DEFAULT NULL,
                requested_model TEXT DEFAULT NULL,
                requested_reasoning_effort TEXT DEFAULT NULL,
                requested_context_window_tokens INTEGER DEFAULT NULL,
                usage_totals TEXT DEFAULT NULL,
                execution_level TEXT DEFAULT 'primary',
                mode TEXT DEFAULT 'wait',
                workspace TEXT DEFAULT '',
                project_id INTEGER NOT NULL REFERENCES projects(id),
                offered_at TIMESTAMPTZ NOT NULL,
                last_heartbeat TIMESTAMPTZ,
                last_tool_call_at TIMESTAMPTZ,
                ended_at TIMESTAMPTZ,
                terminated_at TIMESTAMPTZ
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS work_claims (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                scope TEXT NOT NULL,
                claim_type TEXT,
                claimed_at TIMESTAMPTZ,
                released_at TIMESTAMPTZ,
                release_reason TEXT,
                target_kind TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS path_claims (
                id INTEGER PRIMARY KEY,
                owner_kind TEXT,
                owner_item_id INTEGER,
                owner_session_id TEXT,
                owner_work_claim_id INTEGER,
                registered_by_actor_id INTEGER,
                registered_by_session_id TEXT,
                released_at TIMESTAMPTZ,
                cancelled_at TIMESTAMPTZ,
                release_reason TEXT,
                cancel_reason TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS path_claim_targets (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                claim_id INTEGER
            )
        """)
        conn.execute(
            """
            INSERT INTO harness_sessions
                (session_id, executor, executor_surface, provider, model,
                 execution_level, mode, workspace, project_id, offered_at,
                 last_heartbeat)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                "mac-yoke",
                "claude-code",
                "claude-desktop",
                "anthropic",
                "claude-opus",
                "primary",
                "wait",
                "/Users/testy/code/yoke",
                1,
                "2026-06-30T12:00:00Z",
                "2026-06-30T12:01:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    repo_root = "/Users/testy/code/yoke"
    config = parse_config(config_file, repo_root=repo_root)
    art_config = parse_art_config(config_file, repo_root=repo_root)
    with BoardDB(populated_db) as db:
        payload = collect_board_data(
            db, scope="yoke", config=config, repo_root=repo_root
        )

    assert "session_workspace_aliases" not in payload
    rendered = render_board_from_payload(
        json.loads(json.dumps(payload)),
        scope="yoke",
        config=config,
        art_config=art_config,
        repo_root=repo_root,
    )
    assert "mac-yoke" in rendered
    assert "yoke" in rendered


def test_parity_all_scope_with_zen_and_vision(populated_db, tmp_path):
    """Local VISION labels compose with timeline facts."""
    cfg = tmp_path / "config"
    cfg.write_text(
        textwrap.dedent("""\
        dashboard_velocity=true
        dashboard_weather=true
        dashboard_velocity_meter=true
        timeline_widget=always
    """)
    )
    vision = [("1mo", "autonomous"), ("6mo", "fleet")]
    direct = _direct_render(
        populated_db, "all", str(cfg), seed=3, vision_entries=vision
    )
    fed = _data_fed_render(populated_db, "all", str(cfg), seed=3, vision_entries=vision)
    assert fed == direct


def test_named_payload_accepts_additive_facts(populated_db, config_file):
    config = parse_config(config_file)
    with BoardDB(populated_db) as db:
        payload = collect_board_data(db, scope="yoke", config=config)
    kwargs = dict(scope="yoke", config=config, art_config=ArtConfig(), seed=42)
    before = render_board_from_payload(payload, **kwargs)
    payload["future_section"] = {"value": 7}
    payload["sessions"]["future_fact"] = "unused"
    for widget in payload["dashboard"].values():
        if isinstance(widget, dict):
            widget["future_fact"] = "unused"
    for rows in payload["items"].values():
        for row in rows:
            row["future_fact"] = "unused"
    assert (
        render_board_from_payload(json.loads(json.dumps(payload)), **kwargs) == before
    )
    assert "entries" not in payload


def test_payload_versions_must_match(populated_db, config_file):
    from yoke_core.board.data import BoardDataError

    config = parse_config(config_file)
    with BoardDB(populated_db) as db:
        payload = collect_board_data(db, scope="yoke", config=config)
    payload["version"] = 999
    with pytest.raises(BoardDataError, match="contract"):
        render_board_from_payload(
            payload, scope="yoke", config=config, art_config=ArtConfig()
        )


def test_art_is_client_local(populated_db, config_file):
    config = parse_config(config_file)
    with BoardDB(populated_db) as db:
        payload = collect_board_data(db, scope="yoke", config=config)
    for seed in (1, 99):
        assert render_board_from_payload(
            payload, scope="yoke", config=config, art_config=ArtConfig(), seed=seed
        )

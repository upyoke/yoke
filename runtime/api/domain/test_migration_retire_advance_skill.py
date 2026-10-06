"""Retiring the advance skill refuses live pins and converges lane allowlists."""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest

MIGRATION = importlib.import_module("yoke_core.domain.migrations.0053_retire_advance_skill")


def _definition(skill_id: str, container: str = "skill_bindings", key: str = "skill_id") -> str:
    return json.dumps(
        {
            container: [
                {
                    "from_stage_id": "refined-idea",
                    key: skill_id,
                    "through_stage_id": "reviewed-implementation",
                }
            ],
            "terminal_stage_ids": ["done"],
        }
    )


def database(*, items=(), routing=()):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, public_item_prefix TEXT);
        CREATE TABLE workflow_versions (
            id INTEGER PRIMARY KEY, workflow_id TEXT, version INTEGER,
            definition_json TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER, project_sequence INTEGER,
            status TEXT, workflow_version_id INTEGER
        );
        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY, type TEXT, settings TEXT
        );
        INSERT INTO projects VALUES (1, 'ACME');
        """
    )
    conn.execute(
        "INSERT INTO workflow_versions VALUES (1, 'issue', 7, ?)",
        (_definition("advance"),),
    )
    conn.execute(
        "INSERT INTO workflow_versions VALUES (2, 'issue', 8, ?)",
        (_definition("implement"),),
    )
    conn.execute(
        "INSERT INTO workflow_versions VALUES (3, 'issue', 3, ?)",
        (_definition("advance", *MIGRATION._BINDING_SHAPES[1]),),
    )
    for sequence, (status, version_id) in enumerate(items, start=1):
        conn.execute(
            "INSERT INTO items(project_id, project_sequence, status, "
            "workflow_version_id) VALUES (1, ?, ?, ?)",
            (sequence, status, version_id),
        )
    for settings in routing:
        conn.execute(
            "INSERT INTO project_capabilities(type, settings) VALUES (?, ?)",
            ("session-routing", json.dumps(settings)),
        )
    return conn


def _settings(conn):
    return [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT settings FROM project_capabilities ORDER BY id"
        )
    ]


def test_live_item_pinned_to_advance_refuses_naming_item_and_recovery():
    conn = database(
        items=[("done", 1), ("implementing", 1), ("cancelled", 1), ("idea", 2)],
        routing=[{"lane_paths": {"DARIUS": ["advance"]}}],
    )
    before = _settings(conn)
    with pytest.raises(RuntimeError) as refusal:
        MIGRATION.apply(conn)
    message = str(refusal.value)
    assert "retired_advance_skill_pinned" in message
    assert "ACME-2 (issue@7, implementing)" in message
    assert "ACME-1" not in message and "ACME-3" not in message
    assert "yoke items cancel" in message
    assert _settings(conn) == before


def test_terminal_and_implement_pins_pass_and_lane_actions_converge():
    conn = database(
        items=[("done", 1), ("stopped", 1), ("implementing", 2)],
        routing=[
            {
                "lane_paths": {
                    "DARIUS": ["shepherd", "advance", "dash"],
                    "ALTMAN": ["advance", "implement"],
                },
                "lane_paths_MUSKY": "refine,advance",
            },
            {"lane_paths": {"DARIUS": ["refine"]}},
        ],
    )
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    converged, untouched = _settings(conn)
    assert converged["lane_paths"] == {
        "DARIUS": ["shepherd", "implement", "dash"],
        "ALTMAN": ["implement"],
    }
    assert converged["lane_paths_MUSKY"] == "refine,implement"
    assert untouched == {"lane_paths": {"DARIUS": ["refine"]}}
    stored = list(conn.execute("SELECT settings FROM project_capabilities"))
    MIGRATION.apply(conn)
    assert stored == list(conn.execute("SELECT settings FROM project_capabilities"))


def test_older_executor_binding_shape_is_recognized():
    conn = database(items=[("reviewing-implementation", 3)])
    with pytest.raises(RuntimeError, match=r"ACME-1 \(issue@3, reviewing-implementation\)"):
        MIGRATION.apply(conn)


def test_rewrite_declares_the_serving_build_floor():
    assert MIGRATION.MINIMUM_SERVING_VERSION == "next-release"

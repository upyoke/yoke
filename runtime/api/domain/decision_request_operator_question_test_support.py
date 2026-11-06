# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from unittest.mock import Mock

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection

from yoke_core.domain.decision_request_operator_question import validate, subject_ended

from yoke_core.domain.decision_request_question_filing import (
    file_question,
    list_questions,
)

from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
    withdraw_decision_request,
)

from yoke_core.domain.decision_request_rows import request_row

from yoke_core.domain.decision_requests import RoleAuthority


@pytest.fixture
def conn():
    with decision_request_connection() as value:
        value.executescript("""
            CREATE TABLE harness_sessions (
                session_id TEXT PRIMARY KEY, project_id INTEGER, actor_id INTEGER,
                executor TEXT, ended_at TEXT, terminated_at TEXT
            );
            CREATE TABLE work_claims (
                id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
                scope TEXT, released_at TEXT
            );
            INSERT INTO harness_sessions VALUES ('worker', 10, 1, 'codex', NULL, NULL);
            INSERT INTO harness_sessions VALUES ('other', 10, 1, 'cursor', NULL, NULL);
            INSERT INTO harness_sessions VALUES ('steering', 10, 2, 'claude-code', NULL, NULL);
        """)
        value.execute("INSERT INTO actor_project_roles VALUES (1, 10, 4, 'now')")
        from runtime.api.domain.decision_request_requester_label_test_support import (
            add_holdings_schema,
        )

        add_holdings_schema(value)
        yield value


def filing(**overrides):
    return {
        "kind": "operator_question",
        "subject_type": "session_question",
        "subject_key": "worker:choose",
        "project_id": 10,
        "requesting_session_id": "worker",
        "originator_actor_id": 1,
        "session_id": "worker",
        "role_authorities": [RoleAuthority("project", 10, "owner")],
        "subject_context": {
            "question": "Which color?",
            "options": [
                {"id": "blue", "label": "Blue"},
                {"id": "green", "label": "Green"},
            ],
            "recommended_option": "blue",
        },
        **overrides,
    }

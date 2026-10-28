"""Single-item launches continue across a skill boundary with their claim."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from unittest import mock

import pytest

from yoke_core.domain import conduct_reviewed_handoff as handoff
from yoke_core.domain.session_launch_mandate import (
    compose_single_item_mandate,
    session_has_single_item_mandate,
)

ROOT = Path(__file__).resolve().parents[3]
SKILLS = [
    "shared/stage-handoff.md",
    "refine/update-protocol.md",
    "implement/review.md",
    "polish/advance.md",
    "shepherd/SKILL.md",
    "conduct/simulation-gate-escalation.md",
]


@pytest.mark.parametrize("relative", SKILLS)
def test_skill_teaches_both_claim_branches_and_level_exception(relative):
    text = (ROOT / ".agents/skills/yoke" / relative).read_text()
    assert "single-item mandate for this item, keep the" in text
    assert "claim and run `/yoke {next_skill_id} ITEM` now" in text
    assert "Otherwise show the next-skill line and release" in text
    assert "`level_change` handoff takes precedence: release" in text
    assert "launch the returned successor, and end" in text
    assert "yoke claims work release" not in text


@contextmanager
def launch_db(body, *, bound_session="worker", project_id=1):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE items (id INTEGER, project_id INTEGER);
        CREATE TABLE session_launches
            (project_id INTEGER, registered_session_id TEXT, message_id TEXT);
        CREATE TABLE session_messages (message_id TEXT, body TEXT);
        INSERT INTO items VALUES (42, 1);
    """)
    conn.execute("INSERT INTO session_launches VALUES (?, ?, ?)",
                 (project_id, bound_session, "instruction"))
    conn.execute("INSERT INTO session_messages VALUES (?, ?)",
                 ("instruction", body))
    with mock.patch("yoke_core.domain.project_identity.render_item_ref",
                    return_value="APP-42"):
        try:
            yield conn
        finally:
            conn.close()


def mandate(ref="APP-42"):
    return compose_single_item_mandate(
        public_ref=ref, entrypoint=f"/yoke conduct {ref}",
        remaining_legs="the remaining live bindings",
    )


@pytest.mark.parametrize("body,session,project,expected", [
    (mandate(), "worker", 1, True),
    (mandate("APP-420"), "worker", 1, False),
    (mandate(), "other", 1, False),
    (mandate(), "worker", 2, False),
    ("/yoke conduct APP-42", "worker", 1, False),
    ("", "worker", 1, False),
])
def test_mandate_uses_bound_session_exact_item_and_project(body, session, project, expected):
    with launch_db(body, bound_session=session, project_id=project) as conn:
        assert session_has_single_item_mandate(conn, "worker", 42) is expected


@pytest.mark.parametrize("body,successor,retained", [
    (mandate(), None, True),
    ("/yoke conduct APP-42", None, False),
    (mandate(), {"reason": "level_change"}, False),
])
def test_conduct_claim_policy(body, successor, retained):
    with (
        launch_db(body) as conn,
        mock.patch("yoke_core.domain.db_helpers.connect", return_value=mock.MagicMock(
            __enter__=mock.Mock(return_value=conn))),
        mock.patch("yoke_core.domain.workflow_level_handoff.level_handoff",
                   return_value=successor),
        mock.patch("yoke_core.domain.sessions.release_item_claim_for_execution",
                   return_value={"released": True}) as release,
    ):
        result = handoff._release_conduct_claim(42, session_id="worker")
    assert bool(result.get("retained")) is retained
    assert bool(result.get("released")) is not retained
    assert release.call_count == (0 if retained else 1)


def test_verified_handoff_accepts_retained_claim():
    with (
        mock.patch.object(handoff, "_fetch_status", side_effect=[
            "reviewing-implementation", "reviewed-implementation"]),
        mock.patch.object(handoff, "_run_simulation_gate", return_value=0),
        mock.patch.object(handoff, "_run_status_write", return_value=(0, "")),
        mock.patch.object(handoff, "_release_conduct_claim",
                          return_value={"released": False, "retained": True}),
    ):
        assert handoff.run(42, session_id="worker") == 0

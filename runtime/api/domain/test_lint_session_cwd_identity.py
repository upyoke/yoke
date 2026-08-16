"""Session-cwd identity resolution: cursor-map, unidentified, foreign.

An unidentified caller writing into a claimed lane used to look like a
foreign holder because occupancy compares session ids and treats empty
as "not the occupant". These regressions pin the three outcomes the
write guard owes: cursor-map-only identity may write its own lane, a
truly unidentified caller is denied as identity-resolution failure, and
a genuine foreign caller is still denied as foreign.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    CURSOR_SESSION_MAP_DIR_NAME,
    record_conversation_session,
)
from yoke_core.domain import lint_session_cwd
from yoke_core.domain.lint_session_cwd_foreign_lane import (
    FAILURE_CLASS as FOREIGN_LANE_FAILURE_CLASS,
)
from yoke_core.domain.lint_session_cwd_identity import (
    FAILURE_CLASS as IDENTITY_FAILURE_CLASS,
)
from yoke_core.domain.session_ambient_identity import AMBIENT_ENV_VARS

HOLDER = "sid-holder"
INTRUDER = "sid-intruder"
CONVERSATION = "conv-cursor-only"
HELD_ITEM = 4101


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in (*AMBIENT_ENV_VARS, CURSOR_CONVERSATION_ENV_VAR):
        monkeypatch.delenv(name, raising=False)
    return home


def _held_lane(conn, repo, session_id=HOLDER):
    seed_item(conn, item_id=HELD_ITEM, branch="held-lane", repo_path=repo)
    seed_item_claim(conn, session_id, item_id=HELD_ITEM)
    lane = repo / ".worktrees" / "held-lane"
    lane.mkdir(parents=True, exist_ok=True)
    return lane


def _write(lane, session_id="", conversation_id=""):
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(lane / "src" / "a.py")},
    }
    if session_id:
        payload["session_id"] = session_id
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return lint_session_cwd.evaluate_pre_tool_use(payload)


class TestCursorMapOnlyIdentity:
    def test_own_lane_write_is_allowed(self, conn, repo, isolated_home, monkeypatch):
        record_conversation_session(
            CONVERSATION, HOLDER, isolated_home / CURSOR_SESSION_MAP_DIR_NAME,
        )
        monkeypatch.setenv(CURSOR_CONVERSATION_ENV_VAR, CONVERSATION)
        lane = _held_lane(conn, repo)
        verdict = _write(lane)
        assert verdict.allow is True
        assert verdict.session_id == HOLDER


class TestUnidentifiedCaller:
    def test_denied_as_identity_failure_not_foreign(
        self, conn, repo, isolated_home,
    ):
        lane = _held_lane(conn, repo)
        verdict = _write(lane)
        assert verdict.allow is False
        assert verdict.failure_class == IDENTITY_FAILURE_CLASS
        assert "Identify yourself" in verdict.reason
        assert "not a foreign lane holder" in verdict.reason
        assert "yoke claims work acquire" not in verdict.reason

    def test_main_cwd_registered_adapter_is_allowed(
        self, conn, repo, isolated_home,
    ):
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {
                "command": (
                    "yoke ouroboros field-note append --kind failed "
                    "--evidence 'identity diagnostics'"
                ),
            },
        })
        assert verdict.allow is True


class TestForeignCaller:
    def test_identified_intruder_is_still_foreign(self, conn, repo, isolated_home):
        lane = _held_lane(conn, repo)
        verdict = _write(lane, session_id=INTRUDER)
        assert verdict.allow is False
        assert verdict.failure_class == FOREIGN_LANE_FAILURE_CLASS
        assert HOLDER in verdict.reason
        assert "yoke claims work acquire" in verdict.reason
        assert "identity plumbing" not in verdict.reason


class TestCursorConversationOnPayload:
    def test_mapped_conversation_allows_own_lane(self, conn, repo, isolated_home):
        record_conversation_session(
            CONVERSATION, HOLDER, isolated_home / CURSOR_SESSION_MAP_DIR_NAME,
        )
        lane = _held_lane(conn, repo)
        verdict = _write(
            lane, session_id=CONVERSATION, conversation_id=CONVERSATION,
        )
        assert verdict.allow is True
        assert verdict.session_id == HOLDER

    def test_unmapped_conversation_is_identity_failure(
        self, conn, repo, isolated_home,
    ):
        lane = _held_lane(conn, repo)
        verdict = _write(
            lane, session_id=CONVERSATION, conversation_id=CONVERSATION,
        )
        assert verdict.allow is False
        assert verdict.failure_class == IDENTITY_FAILURE_CLASS
        assert "Identify yourself" in verdict.reason
        assert "not a foreign lane holder" in verdict.reason

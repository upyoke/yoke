"""Identity and transport routing for implementation-entry preflight gates.

The acting-session probe must fail before claim or lane creation unless the
write guards' canonical ambient resolver corroborates the session.
``_run_preflight_gates`` then evaluates its four DB refusal gates through the
transport-aware ``call_dispatcher`` facade (registered ``advance.preflight.*``
internal functions) so the DB reads run server-side over an https control
plane as well as in-process against local Postgres — never a bare local
``db_helpers.connect()`` on the gate path. These tests monkeypatch
``call_dispatcher`` in the gate namespace, assert each gate relays with the
right function id and short-circuit ordering, and prove the operator-facing
block narratives are unchanged. A poisoned ``db_helpers.connect`` proves no
bare local connection is opened on the gate path.
"""

from __future__ import annotations

import io
import json
from typing import Any, Dict, List

import pytest

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    CURSOR_SESSION_MAP_DIR_NAME,
    record_conversation_session,
)
from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_core.engines import advance_implementation_entry as entry
from yoke_core.engines import advance_implementation_preflight_gates as gates

_HARD_BLOCKS = "advance.preflight.hard_blocks"
_AC_PRESENCE = "advance.preflight.ac_presence"
_FILE_BUDGET = "advance.preflight.file_budget"
_SPEC_COVERAGE = "advance.preflight.spec_coverage"

# Synthetic fixture item id. Narratives are built from it via f-strings so no
# literal "YOK-N" appears in assertions (keeps the doc-hygiene drift guard clean).
TEST_ITEM_ID = 42

_PASS_RESULTS: Dict[str, Dict[str, Any]] = {
    _HARD_BLOCKS: {"blockers": []},
    _AC_PRESENCE: {"canonical": 3, "unlabeled": 0, "title": "T"},
    _FILE_BUDGET: {"verdict": "pass", "reason": "covered"},
    _SPEC_COVERAGE: {"is_blocked": False, "missing_paths": []},
}


def _isolate_ambient_identity(monkeypatch, tmp_path):
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(CURSOR_CONVERSATION_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.session_process_anchors.resolve_session_from_ancestry",
        lambda: None,
    )
    return home


def test_unresolvable_identity_refuses_before_item_claim_or_lane(
    monkeypatch, tmp_path, test_db,
):
    _isolate_ambient_identity(monkeypatch, tmp_path)
    monkeypatch.setattr(
        entry, "_read_item", lambda _item_id: pytest.fail("item read ran"),
    )
    out = io.StringIO()
    assert entry.run(TEST_ITEM_ID, session_id="declared", out=out) == 1
    error = json.loads(out.getvalue())["error"]
    assert error["kind"] == gates.IDENTITY_UNRESOLVED
    assert "before work-claim or lane creation" in error["narrative"]
    with test_db.cursor() as cur:
        cur.execute(
            "SELECT (SELECT COUNT(*) FROM work_claims WHERE item_id=%s), "
            "(SELECT COUNT(*) FROM item_worktrees WHERE item_id=%s)",
            (TEST_ITEM_ID, TEST_ITEM_ID),
        )
        assert cur.fetchone() == (0, 0)


def test_env_stamped_identity_proceeds(monkeypatch, tmp_path):
    _isolate_ambient_identity(monkeypatch, tmp_path)
    monkeypatch.setenv("YOKE_SESSION_ID", "session-env")
    assert gates._probe_session_identity("session-env") == (
        "session-env", "", "",
    )


def test_cursor_map_identity_proceeds(monkeypatch, tmp_path):
    home = _isolate_ambient_identity(monkeypatch, tmp_path)
    monkeypatch.setenv(CURSOR_CONVERSATION_ENV_VAR, "conversation-1")
    record_conversation_session(
        "conversation-1", "session-cursor",
        home / CURSOR_SESSION_MAP_DIR_NAME,
    )
    assert gates._probe_session_identity("session-cursor") == (
        "session-cursor", "", "",
    )


def test_explicit_session_must_match_write_guard_identity(monkeypatch, tmp_path):
    _isolate_ambient_identity(monkeypatch, tmp_path)
    monkeypatch.setenv("YOKE_SESSION_ID", "session-ambient")
    _, block_kind, narrative = gates._probe_session_identity("session-other")
    assert block_kind == gates.IDENTITY_MISMATCH
    assert "--session-id must corroborate" in narrative


def _ok(function_id: str, result: Dict[str, Any]) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=function_id, version="v1", result=result,
    )


def _install(monkeypatch, overrides: Dict[str, Dict[str, Any]]):
    """Route call_dispatcher to per-function results; record every call.

    A poisoned ``db_helpers.connect`` fails loudly so a passing gate path
    can only have relayed, never opened a bare local connection.
    """
    calls: List[Dict[str, Any]] = []
    results = {**_PASS_RESULTS, **overrides}

    def fake(**kwargs):
        calls.append(kwargs)
        fid = kwargs["function_id"]
        return _ok(fid, results[fid])

    monkeypatch.setattr(gates, "call_dispatcher", fake)
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda *_a, **_k: pytest.fail("gate path must not open a bare connect"),
    )
    return calls


def test_force_skips_all_gates(monkeypatch):
    calls = _install(monkeypatch, {})
    assert gates._run_preflight_gates(TEST_ITEM_ID, force=True) == (True, "")
    assert calls == []


def test_all_gates_pass_relays_each_in_order(monkeypatch):
    calls = _install(monkeypatch, {})
    ok, narrative = gates._run_preflight_gates(TEST_ITEM_ID, force=False)
    assert (ok, narrative) == (True, "")
    assert [c["function_id"] for c in calls] == [
        _HARD_BLOCKS, _AC_PRESENCE, _FILE_BUDGET, _SPEC_COVERAGE,
    ]
    for call in calls:
        assert call["target"].kind == "item" and call["target"].item_id == TEST_ITEM_ID
    assert calls[0]["payload"] == {"gate_filter": "activation"}


def test_hard_blocks_short_circuits_before_later_gates(monkeypatch):
    calls = _install(
        monkeypatch,
        {_HARD_BLOCKS: {"blockers": [
            "BLOCKED|YOK-99|implementing|t|activation|status:done",
        ]}},
    )
    ok, narrative = gates._run_preflight_gates(TEST_ITEM_ID, force=False)
    assert ok is False
    assert narrative.startswith("Blocked by dependencies:\n  BLOCKED|YOK-99")
    assert [c["function_id"] for c in calls] == [_HARD_BLOCKS]


def test_missing_item_narrative_preserved(monkeypatch):
    _install(
        monkeypatch,
        {_AC_PRESENCE: {"canonical": 0, "unlabeled": 0, "title": None}},
    )
    ok, narrative = gates._run_preflight_gates(TEST_ITEM_ID, force=False)
    assert ok is False
    assert narrative == f"YOK-{TEST_ITEM_ID} not found in DB."


def test_no_acceptance_criteria_narrative_preserved(monkeypatch):
    calls = _install(
        monkeypatch,
        {_AC_PRESENCE: {"canonical": 0, "unlabeled": 0, "title": "T"}},
    )
    ok, narrative = gates._run_preflight_gates(TEST_ITEM_ID, force=False)
    assert ok is False
    assert narrative == (
        f"YOK-{TEST_ITEM_ID} has no acceptance criteria. Add "
        "`## Acceptance Criteria` with `- [ ] AC-N: ...` checkboxes."
    )
    # short-circuits before the File Budget + coverage gates
    assert [c["function_id"] for c in calls] == [_HARD_BLOCKS, _AC_PRESENCE]


def test_file_budget_block_narrative_preserved(monkeypatch):
    calls = _install(
        monkeypatch,
        {_FILE_BUDGET: {
            "verdict": "block",
            "reason": "effective File Budget is missing",
        }},
    )
    ok, narrative = gates._run_preflight_gates(TEST_ITEM_ID, force=False)
    assert (ok, narrative) == (
        False, "BLOCKED: effective File Budget is missing",
    )
    # blocks before the spec-coverage gate
    assert [c["function_id"] for c in calls] == [
        _HARD_BLOCKS, _AC_PRESENCE, _FILE_BUDGET,
    ]


def test_spec_coverage_block_narrative_preserved(monkeypatch):
    calls = _install(
        monkeypatch,
        {_SPEC_COVERAGE: {
            "is_blocked": True,
            "missing_paths": ["runtime/api/x.py", "runtime/api/y.py"],
        }},
    )
    ok, narrative = gates._run_preflight_gates(TEST_ITEM_ID, force=False)
    assert ok is False
    assert narrative == (
        f"BLOCKED: YOK-{TEST_ITEM_ID} File Budget lists 2 path(s) not covered by any "
        "active path_claim.\nMissing: runtime/api/x.py, runtime/api/y.py"
    )
    assert [c["function_id"] for c in calls] == [
        _HARD_BLOCKS, _AC_PRESENCE, _FILE_BUDGET, _SPEC_COVERAGE,
    ]


def test_gate_relay_failure_fails_closed(monkeypatch):
    """A refused gate read raises rather than silently passing the gate."""
    def fake(**kwargs):
        return FunctionCallResponse(
            success=False, function=kwargs["function_id"], version="v1",
            error=FunctionError(code="refused", message="no local db"),
        )

    monkeypatch.setattr(gates, "call_dispatcher", fake)
    with pytest.raises(RuntimeError, match=_HARD_BLOCKS):
        gates._run_preflight_gates(TEST_ITEM_ID, force=False)

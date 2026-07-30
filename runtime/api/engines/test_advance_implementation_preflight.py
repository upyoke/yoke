"""Transport-aware relay routing for the implementation-entry preflight gates.

``_run_preflight_gates`` must evaluate its four refusal gates through the
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

from typing import Any, Dict, List

import pytest

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
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

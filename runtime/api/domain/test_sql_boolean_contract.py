"""Predicate comparison treats ANY-array operands as sets and nothing else."""

from unittest.mock import patch

import pytest

from yoke_core.domain import qa_deployment_scope_schema as scope_schema
from yoke_core.domain.sql_boolean_contract import canonical_boolean_expression

_SCOPE = "item_id IS NOT NULL"
_INDEX = ("idx_live", ("item_id",), _SCOPE)


def _same(left, right):
    return canonical_boolean_expression(left) == canonical_boolean_expression(right)


def test_reordered_any_arrays_compare_equal():
    assert _same(
        "(item_id IS NOT NULL) AND (state = ANY (ARRAY['active'::text, "
        "'walking'::text, 'awaiting_walk_review'::text, 'waiting'::text]))",
        "item_id IS NOT NULL AND state = ANY "
        "(ARRAY['active','awaiting_walk_review','waiting','walking'])",
    )


def test_missing_or_extra_any_elements_still_differ():
    expected = "state = ANY (ARRAY['active','waiting'])"
    assert not _same("state = ANY (ARRAY['waiting'])", expected)
    assert not _same("state = ANY (ARRAY['waiting','active','error'])", expected)


def test_text_outside_any_arrays_stays_order_sensitive():
    assert not _same("COALESCE(a, b) = 'x'", "COALESCE(b, a) = 'x'")
    assert not _same("tags = ARRAY['a','b']", "tags = ARRAY['b','a']")
    assert not _same(
        "note = 'state = ANY (ARRAY[''b'',''a''])'",
        "note = 'state = ANY (ARRAY[''a'',''b''])'",
    )


def _assert_live_index(predicate):
    contract = (("item_id",), predicate, True, True, True)
    with patch.object(scope_schema, "_index_contract", return_value=contract):
        scope_schema._assert_indexes(None, "qa_plan_executions", (_INDEX,))


def test_index_contract_accepts_any_state_order():
    _assert_live_index(
        f"({_SCOPE}) AND (state = ANY (ARRAY['walking'::text, 'waiting'::text, "
        "'awaiting_walk_review'::text, 'active'::text]))"
    )


@pytest.mark.parametrize("states", [
    "'active','waiting','walking'",
    "'active','waiting','walking','awaiting_walk_review','awaiting_agent_review'",
])
def test_index_contract_names_a_wrong_state_set(states):
    with pytest.raises(AssertionError, match="idx_live has wrong predicate"):
        _assert_live_index(f"{_SCOPE} AND state = ANY (ARRAY[{states}])")

"""Implementation-entry File Budget and claim preflight ordering."""

from unittest import mock

import pytest

from yoke_core.engines import advance_implementation_preflight_gates as gates


def _coverage(paths=()):
    return type(
        "Coverage",
        (),
        {"is_blocked": bool(paths), "missing_paths": list(paths)},
    )()


def _preflight(
    *,
    blockers=(),
    acs=(3, 0, "title"),
    budget=None,
    coverage=None,
):
    connect = mock.MagicMock()
    budget = budget or {"verdict": "pass", "reason": "covered"}
    coverage = coverage or _coverage()
    with mock.patch(
        "yoke_core.domain.check_hard_blocks.evaluate_blockers",
        return_value=list(blockers),
    ), mock.patch(
        "yoke_core.domain.check_ac_presence.evaluate_item",
        return_value=acs,
    ), mock.patch.object(
        gates.db_helpers, "connect", connect,
    ), mock.patch(
        "yoke_core.domain.file_budget_required_gate.evaluate",
        return_value=budget,
    ) as budget_gate, mock.patch(
        "yoke_core.domain.path_claim_spec_coverage_gate.evaluate",
        return_value=coverage,
    ) as parity_gate:
        result = gates._run_preflight_gates(42, force=False)
    return result, budget_gate, parity_gate


def test_preflight_force_skips_all():
    assert gates._run_preflight_gates(42, force=True) == (True, "")


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    (
        (
            {"blockers": ["BLOCKED|YOK-99|implementing|t|activation|merged"]},
            "Blocked by dependencies",
        ),
        ({"acs": (0, 0, "title")}, "acceptance criteria"),
        ({"coverage": _coverage(("runtime/api/x.py",))}, "File Budget"),
    ),
)
def test_preflight_blocks_existing_gates(kwargs, fragment):
    (ok, narrative), _budget, _parity = _preflight(**kwargs)

    assert ok is False
    assert fragment in narrative


def test_preflight_blocks_budget_before_claim_parity():
    result, budget_gate, parity_gate = _preflight(
        budget={
            "verdict": "block",
            "reason": "effective File Budget is missing",
        },
    )

    assert result == (False, "BLOCKED: effective File Budget is missing")
    budget_gate.assert_called_once()
    parity_gate.assert_not_called()

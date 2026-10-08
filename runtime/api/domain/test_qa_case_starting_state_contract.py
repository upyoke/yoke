"""Machine-run cases declare where they start, and impossible chains refuse."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_contracts.qa_case_starting_state import (
    StartingStateError,
    chain_baselines,
    normalize_starting_state,
    require_materialized_starting_state,
    require_selected_chains,
    reset_baselines,
    stored_fan_out,
)


def _case(key, runner="host_control", baselines=(), state=None, reason=None):
    return {
        "case_key": key,
        "runner_id": runner,
        "host_baselines": list(baselines),
        "starting_state": state,
        "starting_state_reason": reason,
    }


def _normalize(case):
    return normalize_starting_state(
        case_key=case["case_key"],
        runner_id=case["runner_id"],
        host_baselines=case["host_baselines"],
        starting_state=case["starting_state"],
        starting_state_reason=case["starting_state_reason"],
    )


def test_each_declaration_normalizes_to_its_stored_form() -> None:
    assert _normalize(_case("a", baselines=["fresh-host"])) == ("baseline", None)
    assert _normalize(_case("b", state="inherit")) == ("inherit", None)
    assert _normalize(_case("c", state="as_is", reason=" lab host ")) == (
        "as_is",
        "lab host",
    )
    assert _normalize(_case("d", runner="browser_substrate")) == (None, None)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (_case("none"), "declares no starting state"),
        (_case("bad", state="later"), "is not one of baseline, inherit, as_is"),
        (_case("odd", baselines=["fresh-hose"]), "available baselines: fresh-host"),
        (_case("both", baselines=["fresh-host"], state="inherit"), "never both"),
        (_case("empty", state="baseline"), "with no host_baselines"),
        (_case("why", state="as_is"), "without a starting_state_reason"),
        (_case("extra", state="inherit", reason="x"), "takes no"),
        (
            _case("web", runner="browser_substrate", baselines=["fresh-host"]),
            "only machine-run cases",
        ),
    ],
)
def test_undeclared_or_impossible_declarations_refuse_with_the_choices(
    case, expected
) -> None:
    with pytest.raises(StartingStateError) as refusal:
        _normalize(case)
    assert expected in str(refusal.value)


def test_undeclared_refusal_names_every_choice_and_the_edit_commands() -> None:
    with pytest.raises(StartingStateError) as refusal:
        _normalize(_case("installer"))
    message = str(refusal.value)
    for fragment in (
        "fresh-host, shell-preconfigured",
        '"inherit"',
        '"as_is"',
        "yoke qa plan edit",
        "yoke qa plan-cases replace",
    ):
        assert fragment in message


def test_inheriting_cases_follow_their_predecessors_fan_out() -> None:
    fan_out = chain_baselines(
        [
            _case("open", baselines=["fresh-host", "shell-preconfigured"]),
            _case("follow", state="inherit"),
            _case("found", state="as_is", reason="lab"),
            _case("after-found", state="inherit"),
            _case("web", runner="browser_substrate"),
        ]
    )
    assert fan_out == {
        "open": ["fresh-host", "shell-preconfigured"],
        "follow": ["fresh-host", "shell-preconfigured"],
        "found": [None],
        "after-found": [None],
        "web": [None],
    }


@pytest.mark.parametrize(
    ("cases", "expected"),
    [
        ([_case("first", state="inherit")], "plan's first case"),
        (
            [_case("web", runner="browser_substrate"), _case("next", state="inherit")],
            "must directly follow a machine-run case",
        ),
        (
            [
                _case("walk", runner="agent_mission", baselines=["fresh-host"]),
                _case("after", state="inherit"),
            ],
            "exploratory mission is walked after",
        ),
        (
            [
                _case("check", baselines=["fresh-host"]),
                _case("walk", runner="agent_mission", state="inherit"),
            ],
            "exploratory mission is walked after",
        ),
    ],
)
def test_impossible_chains_refuse(cases, expected) -> None:
    with pytest.raises(StartingStateError) as refusal:
        chain_baselines(cases)
    assert expected in str(refusal.value)


def test_a_selection_keeps_each_inheriting_case_behind_its_predecessor() -> None:
    plan = [
        _case("a", baselines=["fresh-host"]),
        _case("b", state="inherit"),
        _case("c", baselines=["fresh-host"]),
    ]
    require_selected_chains(plan, ["a", "b", "c"])
    require_selected_chains(plan, ["c"])
    for selection in (["b"], ["c", "b"], ["a", "c", "b"]):
        with pytest.raises(StartingStateError) as refusal:
            require_selected_chains(plan, selection)
        assert "select 'a' before it" in str(refusal.value)


def test_only_a_case_opening_a_chain_from_a_baseline_resets() -> None:
    opening = {"starting_state": "baseline", "host_baseline": "fresh-host"}
    assert reset_baselines(opening) == ["fresh-host"]
    assert reset_baselines(opening, continues=True) == []
    inherit = {"starting_state": "inherit", "host_baseline": "fresh-host"}
    assert reset_baselines(inherit) == []
    assert reset_baselines({"starting_state": "as_is", "host_baseline": None}) == []


def test_a_materialized_case_must_carry_a_consistent_declaration() -> None:
    def row(state, baseline):
        return SimpleNamespace(
            requirement_id=7, starting_state=state, host_baseline=baseline
        )

    require_materialized_starting_state(row("baseline", "fresh-host"))
    require_materialized_starting_state(row("inherit", None))
    for state, baseline, expected in (
        (None, "fresh-host", "declares no starting state"),
        ("baseline", None, "disagrees with its host baseline"),
        ("as_is", "fresh-host", "disagrees with its host baseline"),
    ):
        with pytest.raises(StartingStateError) as refusal:
            require_materialized_starting_state(row(state, baseline))
        assert expected in str(refusal.value)
        assert "requirement 7" in str(refusal.value)


def test_stored_fan_out_follows_chains_without_validating() -> None:
    cases = [
        _case("open", baselines=("fresh-host", "shell-preconfigured")),
        _case("follow", state="inherit"),
        _case("found", state="as_is", reason="lab"),
        _case("after-found", state="inherit"),
        _case("undeclared"),
        _case("plain", runner="worktree_run"),
    ]
    assert stored_fan_out(cases) == [
        ["fresh-host", "shell-preconfigured"],
        ["fresh-host", "shell-preconfigured"],
        [None],
        [None],
        [None],
        [None],
    ]

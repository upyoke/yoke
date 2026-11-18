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
        "method_config": {"os": "macos"} if runner == "agent_mission" else {},
        "host_baselines": list(baselines),
        "starting_state": state,
        "starting_state_reason": reason,
    }


def _normalize(case):
    return normalize_starting_state(
        case_key=case["case_key"],
        runner_id=case["runner_id"],
        method_config=case.get("method_config"),
        host_baselines=case["host_baselines"],
        starting_state=case["starting_state"],
        starting_state_reason=case["starting_state_reason"],
    )


def test_each_declaration_normalizes_to_its_stored_form() -> None:
    assert _normalize(_case("a", baselines=["fresh-host"])) == ("baseline", None)
    assert _normalize(_case("b", state="inherit")) == ("inherit", None)
    assert _normalize(_case("d", runner="browser_substrate")) == (None, None)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (_case("none"), "declares no starting state"),
        (_case("bad", state="later"), "is not one of baseline, inherit"),
        (_case("odd", baselines=["fresh-hose"]), "available baselines: fresh-host"),
        (_case("both", baselines=["fresh-host"], state="inherit"), "never both"),
        (_case("empty", state="baseline"), "with no host_baselines"),
        (_case("why", state="as_is", reason="lab"), "is not one of"),
        (_case("extra", state="inherit", reason="x"), "takes no"),
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
        "yoke qa plan edit",
        "yoke qa plan-cases replace",
    ):
        assert fragment in message


def test_inheriting_cases_follow_their_predecessors_fan_out() -> None:
    fan_out = chain_baselines(
        [
            _case("open", baselines=["fresh-host", "shell-preconfigured"]),
            _case("follow", state="inherit"),
            _case("web", runner="browser_substrate"),
        ]
    )
    assert fan_out == {
        "open": ["fresh-host", "shell-preconfigured"],
        "follow": ["fresh-host", "shell-preconfigured"],
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
    assert reset_baselines({**opening, "host_baseline": "shell-preconfigured"}) == [
        "shell-preconfigured"
    ]


def test_a_materialized_case_must_carry_a_consistent_declaration() -> None:
    def row(state, baseline):
        return SimpleNamespace(
            requirement_id=7, starting_state=state, host_baseline=baseline
        )

    require_materialized_starting_state(row("baseline", "fresh-host"))
    require_materialized_starting_state(row("inherit", "fresh-host"))
    for state, baseline, expected in (
        (None, "fresh-host", "declares no valid starting state"),
        ("baseline", None, "disagrees with its host baseline"),
        ("as_is", "fresh-host", "declares no valid starting state"),
        ("inherit", None, "disagrees with its host baseline"),
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


@pytest.mark.parametrize("encoded", [False, True])
def test_inherit_refuses_a_different_driver_with_recovery(encoded):
    import json

    cases = [_case("open", baselines=["fresh-host"]), _case("next", state="inherit")]
    for case, machine in zip(cases, ["mac-lab", "linux-lab"]):
        config = {"test_machine": machine}
        case["method_config"] = json.dumps(config) if encoded else config
    with pytest.raises(StartingStateError, match="inherited_driver_mismatch") as error:
        chain_baselines(cases)
    assert "predecessor's method_config.test_machine" in str(error.value)


def test_a_mission_can_inherit_as_the_chain_tail():
    cases = [
        _case("open", baselines=["fresh-host"]),
        _case("walk", runner="agent_mission", state="inherit"),
    ]
    for case in cases:
        case["method_config"] = {"test_machine": "mac-lab"}
    assert chain_baselines(cases)["walk"] == ["fresh-host"]
    with pytest.raises(StartingStateError, match="no case may inherit after"):
        chain_baselines([*cases, _case("after", state="inherit")])


@pytest.mark.parametrize("runner", ["browser_substrate", "worktree_run", "agent_mission"])
@pytest.mark.parametrize("state", ["as_is", "inherit", "obsolete"])
def test_non_machine_cases_ignore_stale_starting_state(runner, state):
    case = _case("controller", runner=runner, state=state, reason="old host")
    case["method_config"] = {}
    assert _normalize(case) == (None, None)
    assert chain_baselines([case]) == {"controller": [None]}


def _command(runner="worktree_run", config=None, **declared):
    return normalize_starting_state(
        case_key="authorize",
        runner_id=runner,
        method_config=config or {"test_machine": "windows-lab", "command": "true"},
        host_baselines=declared.get("baselines", []),
        starting_state=declared.get("state"),
        starting_state_reason=declared.get("reason"),
    )


def test_host_command_resets_only_a_declared_baseline() -> None:
    state = _command(baselines=["shell-preconfigured"])
    assert state == ("baseline", None)
    assert reset_baselines(
        {"starting_state": state[0], "host_baseline": "shell-preconfigured"}
    ) == ["shell-preconfigured"]
    assert _command(state="inherit") == ("inherit", None)
    for declared in (
        {},
        {"state": "as_is", "reason": "why"},
        {"state": "baseline"},
        {"baselines": ["no-such-baseline"]},
    ):
        with pytest.raises(StartingStateError):
            _command(**declared)
    # A Command that names no Test Machine never starts from a baseline.
    assert _command(config={"command": "true"}, baselines=["fresh-host"]) == (
        None,
        None,
    )

def test_plan_refuses_a_host_command_without_a_baseline():
    case = _case("command", runner="worktree_run")
    case["method_config"] = {"test_machine": "linux-lab", "command": "true"}
    with pytest.raises(StartingStateError, match="declares no starting state"):
        chain_baselines([case])


def test_plan_refuses_as_is_even_with_a_reason():
    with pytest.raises(StartingStateError, match="as_is"):
        chain_baselines([_case("old", state="as_is", reason="lab")])


@pytest.mark.parametrize(
    ("runner", "key", "config"),
    [
        ("agent_mission", "sign-in", {"browser_identities": ["operator"]}),
        ("worktree_run", "authorize", {
            "command": "yoke browser authorize --test-machine linux-lab",
        }),
        ("worktree_run", "remote", {
            "command": "yoke test-machine exec --test-machine linux-lab -- yoke status",
        }),
        ("host_control", "steps", {"steps": [{"argv": ["/bin/yoke", "status"]}]}),
        ("host_control", "terminal-steps", {"steps": [{"send": "yoke status\n"}]}),
        ("host_control", "uninstall", {}),
        ("host_control", "upgrade-project", {}),
    ],
)
def test_yoke_cases_require_shell_preconfigured_on_the_chain_head(runner, key, config):
    follower = _case(key, runner=runner, state="inherit")
    follower["method_config"] = {"test_machine": "linux-lab", **config}
    opener = _case("setup", baselines=["fresh-host"])
    opener["method_config"] = {"test_machine": "linux-lab"}
    with pytest.raises(StartingStateError, match="starting_state_lacks_yoke.*shell-preconfigured"):
        chain_baselines([opener, follower])

    opener["host_baselines"] = ["shell-preconfigured"]
    assert chain_baselines([opener, follower]) == {
        "setup": ["shell-preconfigured"], key: ["shell-preconfigured"]
    }
    assert reset_baselines({"starting_state": "inherit", "host_baseline": "shell-preconfigured"}) == []


def test_mission_cannot_open_from_fresh_host_with_browser_identities():
    case = _case("browser", runner="agent_mission", baselines=["fresh-host"])
    case["method_config"]["browser_identities"] = ["operator"]
    with pytest.raises(StartingStateError, match="starting_state_lacks_yoke.*shell-preconfigured"):
        chain_baselines([case])

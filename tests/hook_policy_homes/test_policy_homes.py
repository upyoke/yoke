"""The policy-home table is complete and both relay halves obey it."""

from __future__ import annotations

import pytest

from yoke_contracts.hook_runner.hook_ordering import HOOK_ORDERING
from yoke_contracts.hook_runner.policy_home import (
    CLIENT_POLICIES,
    POLICY_HOMES,
    PolicyHome,
    PolicyPlacement,
    client_facts_for,
    placement,
)
from yoke_core.hooks.remote_policy import remote_skip_marker
from yoke_harness.hooks import client_facts, local_subset


def _chain_modules() -> set[str]:
    return {
        module
        for matchers in HOOK_ORDERING.values()
        for chain in matchers.values()
        for module in chain
    }


def test_every_chain_policy_has_exactly_one_home() -> None:
    assert _chain_modules() == set(POLICY_HOMES)


def test_unclassified_module_refuses_by_name() -> None:
    with pytest.raises(KeyError, match="has no home"):
        placement("yoke_core.domain.not_a_policy")


def test_server_skips_exactly_the_client_policies() -> None:
    skipped = {m for m in POLICY_HOMES if remote_skip_marker(m) is not None}
    assert skipped == CLIENT_POLICIES


def test_every_client_policy_has_a_client_implementation() -> None:
    implemented = set(local_subset._POLICY_EVALUATORS) | {
        local_subset._SESSION_DISPATCH
    }
    assert implemented == set(CLIENT_POLICIES)


def test_every_named_fact_has_a_client_collector() -> None:
    named = client_facts_for(POLICY_HOMES)
    assert named <= set(client_facts._COLLECTORS)


def test_client_facts_belong_only_to_fact_fed_server_policies() -> None:
    with pytest.raises(ValueError):
        PolicyPlacement(PolicyHome.SERVER, ("_yoke_client_x",))
    with pytest.raises(ValueError):
        PolicyPlacement(PolicyHome.SERVER_WITH_CLIENT_FACTS)
    with pytest.raises(ValueError):
        PolicyPlacement(PolicyHome.CLIENT, ("_yoke_client_x",))


def test_collector_gathers_only_the_chain_facts(monkeypatch) -> None:
    calls: list[str] = []
    for key in list(client_facts._COLLECTORS):
        monkeypatch.setitem(
            client_facts._COLLECTORS,
            key,
            lambda obs, key=key: calls.append(key) or {key: True},
        )
    chain = ["yoke_core.domain.lint_headless_watcher_timeout"]
    facts = client_facts.collect_client_facts("PreToolUse", {}, "claude-code", chain)
    assert calls == list(client_facts_for(chain))
    assert set(facts) == {*client_facts_for(chain), "_yoke_lint_config"}


def test_failing_collector_names_the_fact_and_continues(monkeypatch, capsys) -> None:
    def boom(_obs):
        raise RuntimeError("probe broke")

    key = "_yoke_client_headless_launch"
    monkeypatch.setitem(client_facts._COLLECTORS, key, boom)
    facts = client_facts.collect_client_facts(
        "PreToolUse",
        {},
        "claude-code",
        ["yoke_core.domain.lint_headless_watcher_timeout"],
    )
    assert key not in facts
    err = capsys.readouterr().err
    assert client_facts.FAILURE_MARKER in err and key in err and "probe broke" in err

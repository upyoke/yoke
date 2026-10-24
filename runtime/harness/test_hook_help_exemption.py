"""Help is exempted before dispatch, with the same chain on both relay halves."""

import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands.help_invocation import is_help_only_command
from yoke_contracts.hook_runner.chain_registry import (
    HELP_EXEMPTION_OPTOUTS,
    chain_for,
    help_only_chain,
)
from yoke_contracts.hook_runner.client_facts import HEADLESS_LAUNCH_KEY
from yoke_core.domain import lint_headless_watcher_timeout
from yoke_core.hooks import runner
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import (
    render_claude_decision,
    render_codex_decision,
    render_cursor_decision,
)
from yoke_core.hooks.types import HookDecision, Outcome
from yoke_harness.hooks.client_facts import event_chain


@pytest.mark.parametrize('command', [
    'yoke watch pytest --help', 'yoke watch pytest -h', 'yoke --version',
    'yoke claims work acquire -h', 'yoke items --help',
    'claude --help', '/usr/local/bin/claude --version', 'pytest -h',
])
def test_print_only_commands(command):
    assert is_help_only_command(command)
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}}
    assert event_chain('PreToolUse', payload) == [
        module for module in chain_for('PreToolUse', 'Bash')
        if module in HELP_EXEMPTION_OPTOUTS
    ]


@pytest.mark.parametrize('command', [
    'yoke watch pytest -- tests/', 'yoke watch pytest -- --help',
    'yoke items get SOME-1 --help', 'claude -p x --help',
    'yoke watch pytest --help; yoke watch pytest -- tests/',
    'yoke watch pytest -- tests/ | grep --help',
    'yoke say "$(touch /tmp/example)" --help',
    'yoke dev run python3 --help', 'echo "yoke watch pytest --help"',
    'yoke watch pytest --help > /tmp/output', 'yoke unknown --help',
    'yoke watch pytest --help\nyoke watch pytest -- tests/',
    'claude --help "', '',
])
def test_other_work_keeps_ordinary_guards(command):
    assert not is_help_only_command(command)
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}}
    assert event_chain('PreToolUse', payload) == chain_for('PreToolUse', 'Bash')


@pytest.mark.parametrize('family,renderer', [
    ('claude', render_claude_decision),
    ('codex', render_codex_decision),
    ('cursor', render_cursor_decision),
])
@pytest.mark.parametrize('command,help_only', [
    ('yoke watch pytest --help', True), ('yoke watch pytest -h', True),
    ('yoke say --help', True), ('yoke messages ack -h', True),
    ('yoke watch pytest -- tests/', False),
])
def test_runner_exempts_before_guards_and_retains_delivery(
    monkeypatch, family, renderer, command, help_only,
):
    from yoke_core.hooks import run_tail
    from yoke_contracts.hook_runner import project_scope, guard_scope

    monkeypatch.setattr(project_scope, 'resolve_hook_project_scope',
                        lambda payload: SimpleNamespace(require_project_id=lambda: 1))
    monkeypatch.setattr(guard_scope, 'applicable_chain', lambda chain, project: chain)
    monkeypatch.setattr(run_tail, 'preflight_remote_registration', lambda **kw: None)
    monkeypatch.setattr(run_tail, 'flush_run_tail', lambda **kw: None)
    monkeypatch.setattr(runner, 'record_guard_decision', lambda *a, **kw: None)
    monkeypatch.setattr(runner._mode_gate, 'apply_mode', lambda decision, *a, **kw: decision)
    invoked = []

    def invoke(module, *, context, **kw):
        invoked.append(module)
        decision = (
            lint_headless_watcher_timeout.evaluate(context)
            if module == 'yoke_core.domain.lint_headless_watcher_timeout'
            else HookDecision(outcome=Outcome.NOOP)
        )
        return decision, '', None, (module, {})

    monkeypatch.setattr(runner, 'invoke_module', invoke)
    payload = {
        'tool_name': 'Bash', 'tool_input': {'command': command},
        HEADLESS_LAUNCH_KEY: {"schema": 1, "value": True},
        'agent_type': 'engineer',
    }
    capability = AdapterCapability(
        family=family, payload_parser=json.loads, decision_renderer=renderer,
    )
    text, _ = runner.run_event('PreToolUse', capability=capability,
                               stdin_data=json.dumps(payload))
    if help_only:
        assert invoked == help_only_chain(chain_for('PreToolUse', 'Bash'),
                                          'PreToolUse', True)
        assert 'BLOCKED' not in text
        assert 'yoke_core.domain.observe_pre' in invoked
    else:
        assert 'yoke_core.domain.lint_headless_watcher_timeout' in invoked
        if family == 'claude':
            assert 'lint-headless-watcher-timeout' in text


def test_registry_optout_and_other_events(monkeypatch):
    from yoke_contracts.hook_runner import chain_registry
    monkeypatch.setattr(chain_registry, 'HELP_EXEMPTION_OPTOUTS', frozenset({'guard'}))
    assert help_only_chain(['guard', 'other'], 'PreToolUse', True) == ['guard']
    assert help_only_chain(['guard', 'other'], 'PostToolUse', True) == ['guard', 'other']


def test_every_yoke_command_and_group_help_uses_the_same_exemption():
    from yoke_cli.commands.command_tree import discovery_routes

    for route in discovery_routes():
        for flag in ("-h", "--help", "--version"):
            command = " ".join(("yoke", *route, flag))
            assert is_help_only_command(command), command

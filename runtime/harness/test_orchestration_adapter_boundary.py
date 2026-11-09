"""Runtime orchestration consumes contracts rather than adapter implementations."""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'packages/yoke-core/src/yoke_core'
# Entry adapters collect local facts and render harness output by design.
HOOK_ADAPTERS = {'local_entry.py'}


def test_runtime_orchestration_has_no_adapter_imports():
    files = [p for p in (CORE / 'hooks').glob('*.py')
             if p.name not in HOOK_ADAPTERS and not p.name.endswith('_entry.py')]
    files += [p for p in (CORE / 'engines').glob('*.py')
              if not p.name.startswith('doctor')]
    violations = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([node.module or ''] if isinstance(node, ast.ImportFrom)
                     else [alias.name for alias in node.names]
                     if isinstance(node, ast.Import) else [])
            for name in names:
                if name.split('.')[0] in {'yoke_cli', 'yoke_harness'}:
                    violations.append(f'{path.relative_to(ROOT)}:{node.lineno}: {name}')
    assert not violations, '\n'.join(violations)


@pytest.mark.parametrize('name', [
    'help_invocation', 'identity_relay', 'identity', 'identity_observed',
    'identity_codex_runtime', 'hook_session_lifecycle', 'hook_decision_render',
    'hook_client_facts', 'model_attestation', 'cursor_session_map', 'command_targets',
    'credentialed_git', 'repo_upstream_freshness',
])
def test_runtime_interfaces_resolve_installed_implementations(name):
    from importlib import import_module

    port = import_module(f'yoke_contracts.runtime_ports.{name}')
    assert getattr(port, f'get_{name}')() is not None

"""Keep domain session policy independent of hook runtime composition."""

from __future__ import annotations

import ast
from pathlib import Path

from yoke_core.domain import session_orientation_cursor
from yoke_core.hooks import cursor_payload


def test_domain_imports_only_pure_hook_records_and_formatting():
    import yoke_core.domain

    root = Path(yoke_core.domain.__file__).parent
    pure_modules = {
        "yoke_core.hooks.types",
        "yoke_core.hooks.decision_render",
        "yoke_core.hooks.turn_end_decision_render",
        "yoke_core.hooks.hook_context_compose",
    }
    forbidden = []
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if module.startswith("yoke_core.hooks.") and module not in pure_modules:
                    forbidden.append((path.name, module))
    assert forbidden == []


def test_cursor_orientation_port_loads_installed_hook_parser():
    adapter = session_orientation_cursor.get_cursor_payload()
    assert adapter is cursor_payload
    payload = adapter.parse_payload('{"session_id": "session", "identity_stamped": true}')
    assert payload["session_id"] == "session"
    assert not adapter.is_folded_cursor_session(payload)

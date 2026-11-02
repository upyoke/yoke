"""Bounded selection retains hook registration route consumers."""

from pathlib import Path

from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


def test_registration_selects_route_consumers_when_bounded(tmp_path: Path) -> None:
    source = "packages/yoke-core/src/yoke_core/hooks/registration.py"
    expected = {
        "runtime/api/test_api_hooks_evaluate_level.py",
        "runtime/api/test_api_hooks_evaluate_route_actor.py",
        "runtime/api/test_api_hooks_evaluate_server_guardrails.py",
        "runtime/api/test_api_hooks_session_registration.py",
        "runtime/api/test_machine_scope_hook_context.py",
        "runtime/api/test_api_hooks_evaluate_route.py",
    }
    for relative in {source, *impacted_tests.ALWAYS_RUN_TESTS, *expected}:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n")

    selection = select([source], build_import_index(tmp_path), bounded=True)

    assert expected <= set(selection.files)
    assert (
        f"hook_registration_route_contract:{source}"
        in selection.widening_triggers
    )

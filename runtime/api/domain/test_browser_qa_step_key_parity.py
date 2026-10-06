"""The Python and JS browser runners share one declared step schema."""

from __future__ import annotations

from yoke_contracts.browser_qa_contract import ACTION_STEP_KEYS, SHARED_STEP_KEYS
from yoke_contracts.browser_step_schema import load_schema
from yoke_harness.browser_runtime_home import package_source_root

JS_SCHEMA_PATH = (
    "packages/yoke-harness/src/yoke_harness/browser_runtime/src/step-schema.js"
)


def test_python_keys_are_the_declared_schema() -> None:
    schema = load_schema()
    assert SHARED_STEP_KEYS == frozenset(schema["shared_keys"])
    assert set(ACTION_STEP_KEYS) == set(schema["actions"])
    for action, spec in schema["actions"].items():
        assert ACTION_STEP_KEYS[action] == frozenset(spec["keys"])


def test_js_runner_loads_the_declared_schema_instead_of_a_second_map() -> None:
    source = (package_source_root() / "src" / "step-schema.js").read_text(
        encoding="utf-8"
    )
    assert "browser_step_schema.json" in source
    assert "const ACTION_STEP_KEYS = Object.freeze({" not in source
    assert JS_SCHEMA_PATH.endswith("step-schema.js")

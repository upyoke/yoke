"""Executable configuration snapshots preserve evidence and correction identity."""

import json
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.qa_requirement_pass_currency import (
    METHOD_CONFIG_FIELD,
    METHOD_CONFIG_REVISION_KEY,
    PRESERVED_JSON_FIELD,
    attach_method_config_snapshot,
    bind_correction_identity,
    recorded_method_config,
)
from runtime.api.test_qa_requirement_config_update import _OLD_STEPS, _NEW_STEPS


class TestAttachMethodConfigSnapshot:
    def test_preserves_non_object_json_array(self) -> None:
        attached = json.loads(
            attach_method_config_snapshot("[1,2]", {"steps": _OLD_STEPS})
        )
        assert attached[PRESERVED_JSON_FIELD] == [1, 2]
        assert attached[METHOD_CONFIG_FIELD]["steps"][0]["action"] == "navigate"

    def test_keeps_existing_start_snapshot(self) -> None:
        first = attach_method_config_snapshot("{}", {"steps": _OLD_STEPS})
        second = attach_method_config_snapshot(first, {"steps": _NEW_STEPS})
        recorded = recorded_method_config(second)
        assert recorded is not None
        assert recorded["steps"][1]["action"] == "assert"

    def test_bind_keeps_marker_through_empty_config(self) -> None:
        marked = bind_correction_identity(
            {"steps": _OLD_STEPS}, canonical({"steps": _NEW_STEPS})
        )
        empty = json.loads(bind_correction_identity(marked, canonical({})))
        restored = json.loads(
            bind_correction_identity(empty, canonical({"steps": _NEW_STEPS}))
        )
        assert empty[METHOD_CONFIG_REVISION_KEY] is True
        assert restored[METHOD_CONFIG_REVISION_KEY] is True

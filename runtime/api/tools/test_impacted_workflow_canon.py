"""Workflow canon changes select data-driven stage transition consumers."""

from pathlib import Path

from yoke_core.tools.impacted_tests import build_import_index, select


def test_canon_change_selects_blitz_release_contract(tmp_path: Path) -> None:
    source = "packages/yoke-core/src/yoke_core/domain/builtin_workflow_canon/blitz.json"
    consumer = "runtime/api/test_blitz_release_stage_close.py"
    for relative, body in ((source, "{}"), (consumer, "def test_contract(): pass")):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    selection = select([source], build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral
    assert consumer in selection.files
    assert f"workflow_canon_consumer_contract:{source}" in selection.widening_triggers

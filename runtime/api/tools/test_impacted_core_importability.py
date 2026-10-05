"""All-module wheel import validation accompanies core changes."""

from pathlib import Path

from yoke_core.tools import impacted_tests


def test_core_change_keeps_wheel_boot_when_broad_selection_is_deferred(tmp_path: Path):
    source = "packages/yoke-core/src/yoke_core/domain/example.py"
    companion = "runtime/api/test_engine_wheel_standalone_boot.py"
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    for name in (source, companion, tooling, *impacted_tests.ALWAYS_RUN_TESTS):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n")
    selection = impacted_tests.select(
        [source, tooling], impacted_tests.build_import_index(tmp_path), bounded=True
    )
    assert selection.bounded_deferral
    assert companion in selection.files
    assert f"core_module_importability:{source}" in selection.widening_triggers

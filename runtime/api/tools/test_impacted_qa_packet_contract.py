"""Rendered QA packet consumers survive bounded selection deferral."""

from pathlib import Path

from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


def test_qa_packet_fragment_selects_rendered_consumer_when_tooling_defers(
    tmp_path: Path,
) -> None:
    source = "packages/yoke-core/src/yoke_core/domain/schema_api_context_commands_qa.py"
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    consumer = "runtime/api/domain/test_schema_api_context_qa_examples.py"
    for relative in {source, tooling, consumer, *impacted_tests.ALWAYS_RUN_TESTS}:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n", encoding="utf-8")

    selection = select([source, tooling], build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral is True
    assert consumer in selection.files
    assert f"qa_packet_contract:{source}" in selection.widening_triggers

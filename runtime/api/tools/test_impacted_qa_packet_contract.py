"""Rendered QA packet consumers survive bounded selection deferral."""

from pathlib import Path

import pytest

from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


@pytest.mark.parametrize(
    "fragment,consumer_name",
    [
        ("commands_qa", "test_schema_api_context_qa_examples"),
        ("tables_items", "test_schema_api_context_column_disambiguation"),
    ],
)
def test_packet_fragment_selects_rendered_consumer_when_tooling_defers(
    tmp_path: Path,
    fragment: str,
    consumer_name: str,
) -> None:
    source = f"packages/yoke-core/src/yoke_core/domain/schema_api_context_{fragment}.py"
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    consumer = f"runtime/api/domain/{consumer_name}.py"
    for relative in {source, tooling, consumer, *impacted_tests.ALWAYS_RUN_TESTS}:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n", encoding="utf-8")

    selection = select([source, tooling], build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral is True
    assert consumer in selection.files
    assert f"qa_packet_contract:{source}" in selection.widening_triggers

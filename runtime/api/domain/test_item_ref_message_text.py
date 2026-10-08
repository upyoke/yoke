"""Shipped message text always names work items by their public refs."""

from pathlib import Path

import pytest

from yoke_core.domain.lint_item_ref_message_text import scan_message_text_item_ids


def test_shipped_message_text_has_no_internal_item_names():
    root = Path(__file__).resolve().parents[3]
    hits = scan_message_text_item_ids(root)
    assert not hits, "\n".join(
        f"{hit.path.relative_to(root)}:{hit.line}: {hit.snippet}" for hit in hits
    )


@pytest.mark.parametrize("label", ["member", "members", "deployment member"])
def test_unrendered_values_are_caught_without_id_in_the_variable(tmp_path, label):
    source = tmp_path / "packages" / "example"
    source.mkdir(parents=True)
    (source / "messages.py").write_text(
        f'def message(value):\n    return f"{label} {{value}} needs evidence"\n'
    )
    assert len(scan_message_text_item_ids(tmp_path)) == 1


def test_rendered_refs_and_command_names_are_not_item_interpolations(tmp_path):
    source = tmp_path / "packages" / "example"
    source.mkdir(parents=True)
    (source / "messages.py").write_text(
        "def message(conn, value, run_id):\n"
        '    return f"member {render_item_ref(conn, value)}: remove-item {run_id} PREFIX-N"\n'
    )
    assert scan_message_text_item_ids(tmp_path) == []

"""Teaching audits check packet values and item read projections safely."""

from __future__ import annotations

import pytest

from yoke_cli.product_boundary_teaching import generate_teaching_audit
from yoke_cli.product_boundary_teaching_extract import extract_recipe_rows
from yoke_core.tools.taught_recipe_parse_probe import parse_probe


@pytest.mark.parametrize("field", ["merge_queue", "merge_sha", "merge_commit_sha"])
def test_projection_probe_rejects_unknown_fields_without_dispatch(field, monkeypatch):
    def refuse_dispatch(**kwargs):
        pytest.fail("a teaching probe dispatched a control-plane operation")

    monkeypatch.setattr(
        "yoke_cli.commands.adapters.items.dispatch_and_emit", refuse_dispatch
    )
    ok, function, error = parse_probe(f"yoke items get PREFIX-N {field}")
    assert not ok
    assert function == "items.get.run"
    assert "unknown items column" in error
    assert "merge_queue_landed_at" in error


def test_projection_probe_accepts_current_field_names():
    assert parse_probe(
        "yoke items get PREFIX-N merged_at merge_queue_status merge_queue_landed_at"
    )[0]


def test_packet_string_recipes_are_audited_as_values(tmp_path):
    seed = (
        tmp_path
        / "packages/yoke-core/src/yoke_core/domain/schema_api_context_example.py"
    )
    seed.parent.mkdir(parents=True)
    seed.write_text(
        'RECIPES = ("yoke items " "db-claim amend PREFIX-N",\n'
        '           "yoke items scalar-update PREFIX-N")\n'
    )
    rows = list(extract_recipe_rows(tmp_path, ("**/*.py",)))
    assert [row[2] for row in rows] == [
        "yoke items db-claim amend PREFIX-N",
        "yoke items scalar-update PREFIX-N",
    ]
    audit = generate_teaching_audit(repo_root=tmp_path, smoke_yoke=parse_probe)
    assert len([row for row in audit.surfaces if row.drift_type]) == 2


def test_inline_item_projection_is_audited(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Read `yoke items get PREFIX-N merge_sha`.\n")
    audit = generate_teaching_audit(repo_root=tmp_path, smoke_yoke=parse_probe)
    assert audit.surfaces[0].drift_type == "stale_argument_shape"


def test_process_release_recipe_is_supported():
    assert parse_probe(
        'yoke claims work release --process STRATEGIZE --project PROJECT --reason "abort"'
    )[0]

"""Draft-map proposal from a scanned file inventory.

The survey proposes an enriched map for any repo state: empty trees
get the minimal vocabulary-only map, populated trees get areas from
directory structure and kinds from naming conventions, tests are
exempted, and every guess is disclosed in the notes. Every proposal
must validate against the architecture-model schema.
"""

from __future__ import annotations

from io import StringIO

import pytest

from yoke_cli.commands.adapters.architecture_draft_render import write_architecture_draft
from yoke_core.domain.architecture_map_survey import (
    DRAFT_LAYERS,
    propose_architecture_map,
)
from yoke_core.domain.architecture_model import validate_payload
from yoke_core.domain.architecture_path_context_seed import _classify, _matchers
from yoke_core.domain.path_context import FAMILY_ARCHITECTURE_LAYER


def test_empty_tree_yields_minimal_map() -> None:
    draft = propose_architecture_map([])
    payload = draft["payload"]
    validate_payload(payload)
    assert payload["domains"] == []
    assert [layer["id"] for layer in payload["layers"]] == [
        layer["id"] for layer in DRAFT_LAYERS
    ]
    assert any("Empty tree" in note for note in draft["notes"])


def test_src_layout_groups_areas_and_kinds() -> None:
    draft = propose_architecture_map(
        [
            "src/billing/invoice.py",
            "src/billing/schema_tables.py",
            "src/billing/api_routes.py",
            "src/reporting/summary.py",
            "tests/test_invoice.py",
        ]
    )
    payload = draft["payload"]
    validate_payload(payload)
    by_id = {domain["id"]: domain for domain in payload["domains"]}
    assert set(by_id) == {"billing", "reporting"}
    billing_globs = {
        entry["glob"]: entry["layer"]
        for entry in by_id["billing"]["path_roots"]
    }
    # Minority kinds get parent-scoped patterns before the area
    # catch-all; the catch-all carries the dominant kind.
    assert billing_globs["src/billing/**"] == "domain"
    assert "storage" in billing_globs.values()
    assert "interface" in billing_globs.values()
    assert payload["exemptions"] == [
        {"glob": "tests/**", "family": "architecture_test_surface"},
    ]


def test_guessed_kinds_are_disclosed() -> None:
    draft = propose_architecture_map(["src/billing/invoice.py"])
    assert any(
        "defaulted to the 'domain' kind" in note for note in draft["notes"]
    )


def test_root_level_files_form_a_root_area() -> None:
    draft = propose_architecture_map(["conftest_helper.py"])
    payload = draft["payload"]
    validate_payload(payload)
    assert payload["domains"][0]["id"] == "root"
    assert payload["domains"][0]["path_roots"][-1]["glob"] == "*.py"


def test_nested_test_directories_collapse_to_one_exemption() -> None:
    draft = propose_architecture_map(
        [
            "pkg/tests/test_a.py",
            "pkg/tests/deep/test_b.py",
            "pkg/code.py",
        ]
    )
    exemptions = draft["payload"]["exemptions"]
    assert exemptions == [
        {"glob": "pkg/tests/**", "family": "architecture_test_surface"},
    ]


@pytest.mark.parametrize("dominant", ["storage", "interface", "domain"])
def test_mixed_directory_preserves_layer_precedence(dominant) -> None:
    expected = {
        "invoice.py": "domain",
        "api_routes.py": "interface",
        "schema_api.py": "storage",
        "view_model.py": "storage",
        "Schema_API.py": "storage",
        "API.py": "interface",
        "document.py": "domain",
    }
    extra_name = {"storage": "schema", "interface": "api", "domain": "plain"}[dominant]
    expected.update({f"{extra_name}_{index}.py": dominant for index in range(30)})
    paths = [f"src/billing/{name}" for name in expected]
    draft = propose_architecture_map(paths)
    roots = draft["payload"]["domains"][0]["path_roots"]
    assert len(roots) < len(paths) / 2
    assert {"glob": "src/billing/*schema*.py", "layer": "storage"} in roots
    exemptions, patterns = _matchers(draft["payload"])
    for name, layer in expected.items():
        values = _classify(f"src/billing/{name}", exemptions, patterns)
        assert values[FAMILY_ARCHITECTURE_LAYER]["layer"] == layer, name


def test_directory_hints_and_nested_siblings_keep_their_layers() -> None:
    expected = {
        "pkg/api/plain.py": "interface",
        "pkg/api/schema_routes.py": "storage",
        "pkg/api/deep/plain.py": "interface",
        "pkg/logic/plain.py": "domain",
        "pkg/logic/api.py": "interface",
        "pkg/logic/deep/plain.py": "domain",
        "pkg/logic/deep/store.py": "storage",
        "pkg/docs/schema_api.py": "docs",
        "pkg/storage/plain.py": "domain",
        "pkg/storage/db.py": "storage",
        "api.py": "interface",
        "schema.py": "storage",
        "plain.py": "domain",
    }
    draft = propose_architecture_map(list(expected))
    exemptions, patterns = _matchers(draft["payload"])
    for path, layer in expected.items():
        assert _classify(path, exemptions, patterns)[FAMILY_ARCHITECTURE_LAYER]["layer"] == layer


def test_large_mixed_inventory_has_bounded_complete_human_output() -> None:
    paths = [
        f"packages/service/src/service/domain/{hint}_{index}.py"
        for hint in ("schema", "api", "plain")
        for index in range(600)
    ]
    draft = propose_architecture_map(paths)
    stream = StringIO()
    write_architecture_draft(draft, stream)
    text = stream.getvalue()
    assert len(text.encode()) < 28_000
    roots = draft["payload"]["domains"][0]["path_roots"]
    assert len(roots) <= 4
    assert all(root["glob"].rsplit("/", 1)[-1] in text for root in roots)
    assert all(note in text for note in draft["notes"])


def test_human_draft_groups_paths_with_headings_and_preserves_precedence() -> None:
    import copy

    draft = propose_architecture_map([
        "pkg/api.py", "pkg/schema.py", "pkg/plain.py", "pkg/deep/schema.py",
        "pkg/deep/plain.py",
        "pkg/tests/test_a.py",
    ])
    before = copy.deepcopy(draft)
    stream = StringIO()
    write_architecture_draft({"project_id": "demo", **draft}, stream)
    text = stream.getvalue()
    assert "Project: demo\n## Layers\n" in text
    assert "## Domain pkg\n" in text
    assert "pkg/: *schema*.py [storage]; *api*.py [interface]; *.py [domain]" in text
    assert text.index("pkg/deep/:") < text.index("pkg/: **")
    assert "## Exemptions\npkg/tests/: ** [architecture_test_surface]" in text
    assert "## Notes\n" in text
    assert draft == before


def test_repository_inventory_human_draft_fits_read_limit() -> None:
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    paths = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "*.py"], text=True,
    ).splitlines()
    assert paths
    stream = StringIO()
    write_architecture_draft(propose_architecture_map(paths), stream)
    assert len(stream.getvalue().encode()) < 28_000


def test_compact_draft_round_trips_through_patch(tmp_path) -> None:
    from runtime.api.project_structure_test_helpers import seed_project
    from yoke_core.domain.project_structure import cmd_init, read_structure
    from yoke_core.domain.project_structure_write import apply_patch

    db_path = str(tmp_path / "structure.db")
    cmd_init(db_path=db_path)
    seed_project(db_path, 3, "demo")
    paths = [f"src/billing/{name}.py" for name in ("schema_api", "api", "invoice")]
    payload = propose_architecture_map(paths)["payload"]
    apply_patch("demo", [{
        "op": "put", "family": "architecture_model",
        "attachment": "project", "payload": payload,
    }], db_path=db_path)
    stored = read_structure("demo", family="architecture_model", db_path=db_path)
    assert stored["entries"][0]["payload"] == payload
    exemptions, patterns = _matchers(stored["entries"][0]["payload"])
    assert [
        _classify(path, exemptions, patterns)[FAMILY_ARCHITECTURE_LAYER]["layer"]
        for path in paths
    ] == ["storage", "interface", "domain"]

"""Draft-map proposal from a scanned file inventory.

The survey proposes an enriched map for any repo state: empty trees
get the minimal vocabulary-only map, populated trees get areas from
directory structure and kinds from naming conventions, tests are
exempted, and every guess is disclosed in the notes. Every proposal
must validate against the architecture-model schema.
"""

from __future__ import annotations

from yoke_core.domain.architecture_map_survey import (
    DRAFT_LAYERS,
    propose_architecture_map,
)
from yoke_core.domain.architecture_model import validate_payload


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

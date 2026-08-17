"""Enriched architecture-map payload validation.

Every domain path pattern declares both its area (the domain) and its
kind (the layer); exemption patterns, the package-layout mapping, and
recorded decisions are optional payload sections with closed shapes.
"""

from __future__ import annotations

import copy

import pytest

from yoke_core.domain.architecture_model import (
    PACKAGE_LAYOUTS,
    derive_edges,
    validate_payload,
)
from yoke_core.domain.project_structure import ValidationError


def _enriched_payload() -> dict:
    return {
        "layers": [
            {"id": "storage", "may_depend_on": [], "forbidden_edges": []},
            {
                "id": "service",
                "may_depend_on": ["storage"],
                "forbidden_edges": [],
            },
        ],
        "domains": [
            {
                "id": "billing",
                "path_roots": [
                    {"glob": "src/pkg/billing_store*.py", "layer": "storage"},
                    {"glob": "src/pkg/billing_api*.py", "layer": "service"},
                ],
            },
        ],
        "exemptions": [
            {"glob": "tests/**", "family": "architecture_test_surface"},
        ],
        "cross_cutting_entrypoints": {
            "events": {"approved_modules": ["pkg.events"]},
        },
        "package_roots": {
            "pkg": [
                {"root": "src", "layout": "package_under_root"},
                {"root": "legacy/pkg", "layout": "package_is_root"},
            ],
        },
        "decisions": [
            {"id": "events-gateway", "rationale": "single emission surface"},
        ],
    }


def test_enriched_payload_validates() -> None:
    validate_payload(_enriched_payload())


def test_optional_sections_may_be_absent() -> None:
    payload = _enriched_payload()
    del payload["exemptions"]
    del payload["package_roots"]
    del payload["decisions"]
    validate_payload(payload)


def test_minimal_map_for_an_empty_tree_validates() -> None:
    validate_payload(
        {
            "layers": [
                {"id": "domain", "may_depend_on": [], "forbidden_edges": []},
            ],
            "domains": [],
        }
    )


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (
            lambda p: p["domains"][0]["path_roots"].__setitem__(
                0, "src/pkg/billing_store*.py"
            ),
            "path_roots[0] must be a {glob, layer} object",
        ),
        (
            lambda p: p["domains"][0]["path_roots"][0].__setitem__(
                "layer", "unknown"
            ),
            "must name a declared layer",
        ),
        (
            lambda p: p["domains"][0]["path_roots"][0].__setitem__("glob", " "),
            ".glob must be a non-empty string",
        ),
        (
            lambda p: p["exemptions"][0].__setitem__("family", "not_a_family"),
            ".family must be one of",
        ),
        (
            lambda p: p["exemptions"].__setitem__(0, "tests/**"),
            "must be a {glob, family} object",
        ),
        (
            lambda p: p["package_roots"]["pkg"][0].__setitem__(
                "layout", "flat"
            ),
            ".layout must be one of",
        ),
        (
            lambda p: p["package_roots"].__setitem__("pkg", []),
            "non-empty list of {root, layout} objects",
        ),
        (
            lambda p: p["decisions"][0].__setitem__("rationale", ""),
            ".rationale must be a non-empty string",
        ),
    ],
)
def test_shape_misses_are_rejected(mutate, fragment) -> None:
    payload = copy.deepcopy(_enriched_payload())
    mutate(payload)
    with pytest.raises(ValidationError, match="architecture_model"):
        try:
            validate_payload(payload)
        except ValidationError as exc:
            assert fragment in str(exc)
            raise


def test_layer_rules_still_project_edges() -> None:
    allowed, forbidden = derive_edges(_enriched_payload())
    assert ("service", "storage") in allowed
    assert forbidden == frozenset()


def test_package_layout_vocabulary_is_closed() -> None:
    assert PACKAGE_LAYOUTS == {"package_under_root", "package_is_root"}

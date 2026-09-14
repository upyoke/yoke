"""The write boundary for ``project-policy`` settings.

``title_max_length`` and ``disposable_generated_paths`` are the validated
keys in this document today: a project-scoped title-length limit, and the
checkout-relative paths a project declares safe for the shared lane
residue policy to treat as disposable. This is the boundary a rejected
save must never write through — the shared CAS merge/set loop only commits
the canonicalized text this boundary returns, so a raised error here
leaves the previously stored document untouched.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.project_contract.project_keys import (
    PROJECT_POLICY_CAPABILITY,
)
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)


def test_minimum_value_is_accepted():
    canonical = canonicalize_capability_settings(
        PROJECT_POLICY_CAPABILITY, json.dumps({"title_max_length": 10})
    )
    assert json.loads(canonical)["title_max_length"] == 10


def test_below_minimum_is_rejected():
    with pytest.raises(ValueError, match="at least 10"):
        canonicalize_capability_settings(
            PROJECT_POLICY_CAPABILITY, json.dumps({"title_max_length": 9})
        )


def test_non_integer_is_rejected():
    with pytest.raises(ValueError, match="integer"):
        canonicalize_capability_settings(
            PROJECT_POLICY_CAPABILITY, json.dumps({"title_max_length": "lots"})
        )


def test_non_integral_float_is_rejected_rather_than_truncated():
    with pytest.raises(ValueError, match="integer"):
        canonicalize_capability_settings(
            PROJECT_POLICY_CAPABILITY, json.dumps({"title_max_length": 10.5})
        )


def test_bool_is_rejected():
    with pytest.raises(ValueError, match="integer"):
        canonicalize_capability_settings(
            PROJECT_POLICY_CAPABILITY, json.dumps({"title_max_length": True})
        )


def test_other_keys_pass_through_unvalidated():
    canonical = canonicalize_capability_settings(
        PROJECT_POLICY_CAPABILITY,
        json.dumps({"title_max_length": 25, "wip_cap": 5}),
    )
    parsed = json.loads(canonical)
    assert parsed["wip_cap"] == 5
    assert parsed["title_max_length"] == 25


def test_document_without_title_max_length_is_untouched():
    canonical = canonicalize_capability_settings(
        PROJECT_POLICY_CAPABILITY, json.dumps({"wip_cap": 5})
    )
    assert json.loads(canonical) == {"wip_cap": 5}


def test_disposable_generated_paths_accepted():
    canonical = canonicalize_capability_settings(
        PROJECT_POLICY_CAPABILITY,
        json.dumps({"disposable_generated_paths": ["docs/atlas.md"]}),
    )
    assert json.loads(canonical)["disposable_generated_paths"] == ["docs/atlas.md"]


def test_disposable_generated_paths_traversal_rejected():
    with pytest.raises(ValueError, match="traverse"):
        canonicalize_capability_settings(
            PROJECT_POLICY_CAPABILITY,
            json.dumps({"disposable_generated_paths": ["../outside"]}),
        )


def test_disposable_generated_paths_non_list_rejected():
    with pytest.raises(ValueError, match="JSON array"):
        canonicalize_capability_settings(
            PROJECT_POLICY_CAPABILITY,
            json.dumps({"disposable_generated_paths": "docs/atlas.md"}),
        )

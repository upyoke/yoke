"""Validation for the ``disposable_generated_paths`` project-policy key.

Mirrors ``test_title_policy.py``'s scope: this module stays DB-free, so
these tests exercise only the shared validator both the settings-save path
and the read-side resolver call.
"""

from __future__ import annotations

import pytest

from yoke_contracts.project_contract.disposable_generated_paths_policy import (
    DISPOSABLE_GENERATED_PATHS_DEFAULT,
    disposable_generated_paths_setting_error,
    parsed_disposable_generated_paths,
)


def test_default_is_empty():
    assert DISPOSABLE_GENERATED_PATHS_DEFAULT == []


@pytest.mark.parametrize(
    "value",
    [
        [],
        ["docs/atlas.md"],
        [".yoke/strategy"],
        ["docs/atlas.md", ".yoke/strategy"],
        ["nested/generated/dir"],
    ],
)
def test_valid_declarations_pass(value):
    assert disposable_generated_paths_setting_error(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "docs/atlas.md",
        {"path": "docs/atlas.md"},
        None,
        42,
    ],
)
def test_non_list_value_rejected(value):
    error = disposable_generated_paths_setting_error(value)
    assert error is not None
    assert "JSON array" in error


@pytest.mark.parametrize(
    "entry",
    [
        "",
        "   ",
        123,
        None,
    ],
)
def test_non_string_or_empty_entry_rejected(entry):
    error = disposable_generated_paths_setting_error([entry])
    assert error is not None
    assert "non-empty strings" in error


@pytest.mark.parametrize(
    "entry",
    [
        "/etc/passwd",
        "/absolute/path",
        "C:/Windows",
    ],
)
def test_absolute_entry_rejected(entry):
    error = disposable_generated_paths_setting_error([entry])
    assert error is not None
    assert "checkout-relative" in error


@pytest.mark.parametrize(
    "entry",
    [
        "../outside",
        "docs/../../etc",
        "..",
    ],
)
def test_traversal_entry_rejected(entry):
    error = disposable_generated_paths_setting_error([entry])
    assert error is not None
    assert "traverse" in error


def test_parsed_normalizes_and_strips_dot_segments():
    parsed = parsed_disposable_generated_paths(
        ["./docs/atlas.md", "docs//nested/./generated/"]
    )
    assert parsed == ("docs/atlas.md", "docs/nested/generated")


def test_parsed_fails_closed_on_invalid_declaration():
    assert parsed_disposable_generated_paths("not-a-list") == ()
    assert parsed_disposable_generated_paths(["../outside"]) == ()

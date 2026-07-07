"""Tests for the shared label-color contract (defaults + resolution helpers)."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_contract.label_policy import (
    DEFAULT_LABEL_COLORS,
    REPO_LABEL_DEFINITIONS,
    overrides_delta,
    parse_labels,
    read_labels_file,
    resolve_color,
)


def test_default_map_covers_every_definition_key() -> None:
    for _category, key, value, _description in REPO_LABEL_DEFINITIONS:
        assert DEFAULT_LABEL_COLORS[key] == value


def test_default_map_has_generic_families() -> None:
    for key in (
        "label_color_status",
        "label_color_source",
        "label_color_owner",
        "label_color_worktree",
        "label_color_frozen",
    ):
        assert key in DEFAULT_LABEL_COLORS


def test_resolve_color_precedence() -> None:
    assert resolve_color("label_color_status", {"label_color_status": "X"}, "Y") == "X"
    assert (
        resolve_color("label_color_status", {}, "Y")
        == DEFAULT_LABEL_COLORS["label_color_status"]
    )
    assert resolve_color("label_color_unknown", {}, "Y") == "Y"
    assert resolve_color("label_color_unknown", None, None) is None


def test_overrides_delta_drops_default_restatements() -> None:
    file_values = {
        # equal to the default (case-insensitively) -> not an override
        "label_color_status": DEFAULT_LABEL_COLORS["label_color_status"].lower(),
        # genuine override
        "label_color_owner": "AABBCC",
        # unknown key -> treated as an override
        "label_color_unknown": "FFFFFF",
    }
    assert overrides_delta(file_values) == {
        "label_color_owner": "AABBCC",
        "label_color_unknown": "FFFFFF",
    }


def test_parse_labels_handles_comments_and_quotes() -> None:
    text = (
        "# header comment\n"
        "label_color_status=AABBCC\n"
        "label_color_owner='112233'  # trailing comment\n"
        "\n"
        "bogus line without equals\n"
    )
    assert parse_labels(text) == {
        "label_color_status": "AABBCC",
        "label_color_owner": "112233",
    }


def test_read_labels_file_missing_returns_empty(tmp_path: Path) -> None:
    assert read_labels_file(tmp_path / "nope") == {}


def test_read_labels_file_parses(tmp_path: Path) -> None:
    labels = tmp_path / "labels"
    labels.write_text("label_color_status=AABBCC\n", encoding="utf-8")
    assert read_labels_file(labels) == {"label_color_status": "AABBCC"}

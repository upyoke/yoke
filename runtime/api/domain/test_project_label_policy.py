"""Tests for the server-side color resolver + per-request override whiteboard."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_contract.label_policy import DEFAULT_LABEL_COLORS
from yoke_core.domain import project_label_policy


# --- explicit policy_path (operator/debug + tests) ---


def test_get_color_reads_explicit_policy_path(tmp_path: Path) -> None:
    labels = tmp_path / "labels"
    labels.write_text("label_color_status=ABC123\n", encoding="utf-8")
    assert project_label_policy.get_color(
        "label_color_status", "C5DEF5", policy_path=labels
    ) == "ABC123"


def test_get_color_strips_comments_and_quotes(tmp_path: Path) -> None:
    labels = tmp_path / "labels"
    labels.write_text("label_color_type_epic='5319E7'  # purple\n", encoding="utf-8")
    assert project_label_policy.get_color(
        "label_color_type_epic", "000000", policy_path=labels
    ) == "5319E7"


def test_get_color_defaults_when_file_or_key_missing(tmp_path: Path) -> None:
    assert project_label_policy.get_color(
        "label_color_status", "C5DEF5", policy_path=tmp_path / "missing"
    ) == "C5DEF5"


# --- server-side pure resolution: request override-else-contract-default ---


def test_get_color_override_wins() -> None:
    # Request-carried override beats the contract default — no file, no repo root.
    assert (
        project_label_policy.get_color(
            "label_color_status", "C5DEF5", overrides={"label_color_status": "ABCDEF"}
        )
        == "ABCDEF"
    )


def test_get_color_uses_contract_default_when_no_override() -> None:
    # A known key with no override resolves to the shared contract default, not
    # the caller's fallback — so priority labels get their real color server-side.
    assert (
        project_label_policy.get_color("label_color_priority_high", "C5DEF5")
        == DEFAULT_LABEL_COLORS["label_color_priority_high"]
    )


def test_get_color_unknown_key_uses_caller_default() -> None:
    assert (
        project_label_policy.get_color("label_color_unknown_xyz", "123456") == "123456"
    )


# --- request-scoped override delivery (the per-request "whiteboard") ---


def test_request_overrides_deliver_to_get_color() -> None:
    assert project_label_policy.get_color("label_color_status", "C5DEF5") == "C5DEF5"
    with project_label_policy.request_overrides({"label_color_status": "FF0000"}):
        assert (
            project_label_policy.get_color("label_color_status", "C5DEF5") == "FF0000"
        )
    # Wiped after the block — no leak into the next request.
    assert project_label_policy.get_color("label_color_status", "C5DEF5") == "C5DEF5"


def test_explicit_overrides_beat_the_whiteboard() -> None:
    with project_label_policy.request_overrides({"label_color_status": "FF0000"}):
        assert (
            project_label_policy.get_color(
                "label_color_status",
                "C5DEF5",
                overrides={"label_color_status": "00FF00"},
            )
            == "00FF00"
        )

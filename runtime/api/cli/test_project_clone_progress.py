"""User-facing progress for anonymous and App-authorized clones."""

from __future__ import annotations

from yoke_cli.config import project_clone_support as clone


def test_clone_progress_lines_clean_clone() -> None:
    lines = clone.clone_progress_lines(
        "acme/widgets",
        clone.CloneOutcome(used_token=False, origin_url="x"),
    )
    assert lines == ["  Cloning acme/widgets…", "  ✓ Cloned."]


def test_clone_progress_lines_token_fallback_is_informational() -> None:
    lines = clone.clone_progress_lines(
        "acme/widgets",
        clone.CloneOutcome(used_token=True, origin_url="x"),
    )
    assert lines == [
        "  Cloning acme/widgets…",
        "  Anonymous access couldn't reach it — used connected GitHub App access.",
        "  ✓ Cloned.",
    ]

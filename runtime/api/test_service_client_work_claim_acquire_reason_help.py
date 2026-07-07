"""Tests for the acquire-intent vocabulary surfaced on ``claim-work --reason``."""

from __future__ import annotations

from yoke_core.api.service_client_work_claim_acquire_reason_help import (
    ACQUIRE_INTENT_REASONS,
    CLAIM_WORK_DESCRIPTION,
    render_acquire_reason_help_text,
)


def test_acquire_intent_reasons_are_unique_and_non_empty():
    assert ACQUIRE_INTENT_REASONS, "vocabulary must not be empty"
    assert len(set(ACQUIRE_INTENT_REASONS)) == len(ACQUIRE_INTENT_REASONS), (
        "duplicate values would conflate Ouroboros buckets"
    )
    for value in ACQUIRE_INTENT_REASONS:
        assert value == value.strip(), (
            f"intent reason has surrounding whitespace: {value!r}"
        )
        assert value, "empty reason value is not allowed"


def test_render_acquire_reason_help_text_lists_every_value_one_per_line():
    rendered = render_acquire_reason_help_text()
    # Free-text remains valid wording stays in place.
    assert "free text remains valid" in rendered.lower()
    # Each value renders on its own bullet line so argparse cannot mid-word-wrap.
    for value in ACQUIRE_INTENT_REASONS:
        assert f"\n  - {value}" in rendered, (
            f"missing bullet for {value!r} in rendered help"
        )


def test_claim_work_description_includes_target_shapes_and_worked_example():
    """The description must teach the three target shapes + a concrete YOK-N."""
    assert "--item YOK-N" in CLAIM_WORK_DESCRIPTION
    assert "--epic-task" in CLAIM_WORK_DESCRIPTION
    assert "--task-num" in CLAIM_WORK_DESCRIPTION
    assert "--process" in CLAIM_WORK_DESCRIPTION
    # Worked example carries a concrete YOK-N per AC-2 canonical shape.
    assert "YOK-N" in CLAIM_WORK_DESCRIPTION
    assert "claim-work" in CLAIM_WORK_DESCRIPTION


def test_claim_work_help_text_renders_through_argparse():
    """Smoke test: the ``claim-work --help`` exit path returns 0 and prints
    the description + the vocabulary bullets.
    """
    import io
    from contextlib import redirect_stdout

    from yoke_core.api.service_client_work_claims import cmd_claim_work

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cmd_claim_work(["--help"])
    out = buf.getvalue()

    assert rc == 0
    # Description teaches the target shapes.
    assert "Acquire a typed work claim" in out
    assert "YOK-N" in out
    # Vocabulary lines surface.
    for value in ACQUIRE_INTENT_REASONS:
        assert value in out

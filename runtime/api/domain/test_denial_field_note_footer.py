"""Tests for ``denial_field_note_footer.append_field_note_footer``.

Locks the contract the lints depend on: the check id and FOOTER are appended
once, recovery text is preserved, and anonymous denials are rejected.
"""

from __future__ import annotations

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_contracts.field_note_text import FOOTER
from yoke_contracts.hook_runner.denial_identity import check_id_line


def test_appends_footer_to_non_empty_denial() -> None:
    result = append_field_note_footer("Lint denied: bad shape.", rule_id="lint-foo")
    assert result == (
        f"Lint denied: bad shape.\n\n{check_id_line('lint-foo')}\n\n{FOOTER}"
    )


def test_appended_footer_references_field_note_append_cli() -> None:
    """Footer text routes operators to the canonical field-note CLI shape."""
    result = append_field_note_footer("Lint denied.", rule_id="lint-foo")
    assert "yoke ouroboros field-note append" in result


def test_appended_footer_does_not_reference_retired_surfaces() -> None:
    """No retired-name residue leaks into denial text. Literals built
    dynamically so the obsoleted-terms grep stays clean."""
    result = append_field_note_footer("Lint denied.", rule_id="lint-foo")
    retired_dashed = "-".join(("recipe", "event"))
    retired_underscored = "_".join(("recipe", "feedback"))
    assert retired_dashed not in result
    assert retired_underscored not in result


def test_empty_denial_returns_blank_plus_footer() -> None:
    """An empty denial still gets the footer — the footer alone never wins."""
    result = append_field_note_footer("", rule_id="lint-bar")
    assert result == f"\n\n{check_id_line('lint-bar')}\n\n{FOOTER}"
    assert FOOTER in result


def test_multiline_denial_text_is_preserved() -> None:
    body = "Line one.\nLine two.\nLine three."
    result = append_field_note_footer(body, rule_id="lint-baz")
    assert result == f"{body}\n\n{check_id_line('lint-baz')}\n\n{FOOTER}"
    assert result.startswith("Line one.")
    assert result.endswith(FOOTER)


def test_idempotent_short_circuits_existing_footer() -> None:
    """Passing already-footered text returns it unchanged (no double-append)."""
    once = append_field_note_footer("Denial.", rule_id="lint-foo")
    twice = append_field_note_footer(once, rule_id="lint-foo")
    assert once == twice
    # FOOTER appears exactly once.
    assert twice.count(FOOTER) == 1


def test_idempotent_short_circuits_with_trailing_newline() -> None:
    """A legacy footer-only message gains identity once, preserving newline."""
    base = f"Denial.\n\n{FOOTER}\n"
    result = append_field_note_footer(base, rule_id="lint-foo")
    assert result.endswith("\n")
    assert check_id_line("lint-foo") in result
    assert result.count(FOOTER) == 1
    assert append_field_note_footer(result, rule_id="lint-foo") == result


def test_rule_id_changes_the_reported_check_identity() -> None:
    text = "Denial here."
    a = append_field_note_footer(text, rule_id="lint-alpha")
    b = append_field_note_footer(text, rule_id="lint-beta")
    assert check_id_line("lint-alpha") in a
    assert check_id_line("lint-beta") in b
    assert a != b


def test_empty_rule_id_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="cannot be empty"):
        append_field_note_footer("Denied.", rule_id="")

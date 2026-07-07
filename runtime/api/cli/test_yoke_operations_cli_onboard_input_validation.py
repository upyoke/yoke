"""Inline input validators for the ``yoke onboard`` wizard's free-text steps.

Each validator returns None for an acceptable value and a short user-facing error
string otherwise, so the wizard can reject bad input inline (stay on the step)
instead of deferring the failure to Apply. The filesystem validators run against
real temp paths; the format validators are pure.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import onboard_input_validation as v


# ── clone target folder (must be empty/new with a writable parent) ───────


def test_clone_folder_accepts_a_new_path(tmp_path: Path) -> None:
    assert v.validate_clone_target_folder(str(tmp_path / "fresh")) is None


def test_clone_folder_accepts_an_existing_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert v.validate_clone_target_folder(str(empty)) is None


def test_clone_folder_rejects_a_non_empty_dir(tmp_path: Path) -> None:
    full = tmp_path / "full"
    full.mkdir()
    (full / "file.txt").write_text("x", encoding="utf-8")
    error = v.validate_clone_target_folder(str(full))
    assert error is not None
    assert "already has files" in error


def test_clone_folder_rejects_a_regular_file(tmp_path: Path) -> None:
    file = tmp_path / "f.txt"
    file.write_text("x", encoding="utf-8")
    error = v.validate_clone_target_folder(str(file))
    assert error is not None
    assert "file, not a folder" in error


def test_clone_folder_rejects_an_unwritable_parent() -> None:
    # /proc never exists on macOS and is not writable where it does — the parent
    # walk lands on a non-writable ancestor.
    error = v.validate_clone_target_folder("/this-root-is-not-writable/x/y")
    assert error is not None
    assert "can't write" in error


def test_clone_folder_rejects_empty() -> None:
    assert v.validate_clone_target_folder("   ") is not None


# ── create / existing-folder target (file + writability, but adopt-friendly) ─


def test_create_folder_accepts_a_new_path(tmp_path: Path) -> None:
    assert v.validate_create_target_folder(str(tmp_path / "new")) is None


def test_create_folder_accepts_an_existing_non_empty_dir(tmp_path: Path) -> None:
    # Existing content is fine for create-new — the flow redirects it to adopt.
    full = tmp_path / "existing"
    full.mkdir()
    (full / "f.txt").write_text("x", encoding="utf-8")
    assert v.validate_create_target_folder(str(full)) is None


def test_create_folder_rejects_a_regular_file(tmp_path: Path) -> None:
    file = tmp_path / "f.txt"
    file.write_text("x", encoding="utf-8")
    error = v.validate_create_target_folder(str(file))
    assert error is not None
    assert "file, not a folder" in error


def test_create_folder_rejects_an_unwritable_parent() -> None:
    error = v.validate_create_target_folder("/this-root-is-not-writable/x/y")
    assert error is not None
    assert "can't write" in error


# ── slug (lowercase-hyphen) ──────────────────────────────────────────────


def test_slug_accepts_lowercase_hyphenated() -> None:
    assert v.validate_slug("my-project") is None
    assert v.validate_slug("widgets") is None
    assert v.validate_slug("proj-2") is None


def test_slug_rejects_uppercase_and_spaces() -> None:
    assert v.validate_slug("My Project") is not None
    assert v.validate_slug("UPPER") is not None
    assert v.validate_slug("trailing-") is not None
    assert v.validate_slug("--double") is not None
    assert v.validate_slug("") is not None


def test_slug_error_names_the_shape() -> None:
    error = v.validate_slug("Bad Slug")
    assert error is not None
    assert "lowercase" in error


def test_slug_rejects_overlong_values() -> None:
    assert v.validate_slug("a" * v.PROJECT_SLUG_MAX_LENGTH) is None
    error = v.validate_slug("a" * (v.PROJECT_SLUG_MAX_LENGTH + 1))
    assert error is not None
    assert str(v.PROJECT_SLUG_MAX_LENGTH) in error


# ── display name ─────────────────────────────────────────────────────────


def test_display_name_requires_non_blank_text() -> None:
    assert v.validate_display_name("Project") is None
    assert v.validate_display_name("  Project  ") is None
    error = v.validate_display_name("   ")
    assert error is not None
    assert "display name" in error


# ── prefix (uppercase-alnum, 2-6 chars, leading letter) ──────────────────


def test_prefix_accepts_typical_shapes() -> None:
    assert v.validate_prefix("PROJ") is None
    assert v.validate_prefix("YOK") is None
    assert v.validate_prefix("AB") is None
    # Lowercase is normalized to upper for the check, so a lowercase entry passes.
    assert v.validate_prefix("proj") is None


def test_prefix_rejects_bad_shapes() -> None:
    assert v.validate_prefix("A") is not None            # too short
    assert v.validate_prefix("TOOLONG") is not None      # >6
    assert v.validate_prefix("1ABC") is not None          # leading digit
    assert v.validate_prefix("PR-OJ") is not None         # hyphen
    assert v.validate_prefix("") is not None


# ── branch name shape ────────────────────────────────────────────────────


def test_branch_accepts_common_names() -> None:
    assert v.validate_branch("main") is None
    assert v.validate_branch("master") is None
    assert v.validate_branch("release/2.0") is None
    assert v.validate_branch("feature_x") is None


def test_branch_rejects_malformed_names() -> None:
    assert v.validate_branch("") is not None
    assert v.validate_branch("has space") is not None
    assert v.validate_branch("/leading-slash") is not None
    assert v.validate_branch("trailing-slash/") is not None
    assert v.validate_branch("trailing-dot.") is not None
    assert v.validate_branch("double..dot") is not None
    assert v.validate_branch("bad~tilde") is not None
    assert v.validate_branch("@") is not None
    assert v.validate_branch(" leading-space") is not None

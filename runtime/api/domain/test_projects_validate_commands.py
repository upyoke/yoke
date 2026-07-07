"""Pure-unit tests for ``yoke_core.domain.projects`` test-command validator.

Targets the validator helper directly (no DB round-trip) plus the output
format contract. DB-backed integration tests live in the sibling
test_projects_validate_commands_db.py.
"""

from __future__ import annotations

import stat
from pathlib import Path

from yoke_core.domain.projects import (
    TestCommandResult,
    _validate_test_command,
    format_validation_block,
)


def _make_script(path: Path) -> None:
    """Create an executable shell script at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env sh\necho test\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# Unit tests for _validate_test_command (direct helper)
# ---------------------------------------------------------------------------


class TestValidateTestCommandUnit:
    """Test the pure validator helper directly, with no DB round-trip."""

    def test_valid_sh_script_resolves(self, tmp_path: Path) -> None:
        _make_script(tmp_path / "scripts/run-tests.sh")
        result = _validate_test_command(
            "quick",
            "sh scripts/run-tests.sh --fast",
            str(tmp_path),
        )
        assert result.status == "valid", result.detail
        assert result.detail == ""

    def test_valid_npm_requires_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name":"x"}\n')
        result = _validate_test_command(
            "e2e", "npm run test:e2e", str(tmp_path)
        )
        assert result.status == "valid"

    def test_empty_value_returns_empty(self, tmp_path: Path) -> None:
        for val in ("", "   ", None):
            result = _validate_test_command("quick", val, str(tmp_path))
            assert result.status == "empty"
            assert result.detail == ""

    def test_null_literal_returns_empty(self, tmp_path: Path) -> None:
        result = _validate_test_command("quick", "null", str(tmp_path))
        assert result.status == "empty"

    def test_missing_sh_script_invalid(self, tmp_path: Path) -> None:
        result = _validate_test_command(
            "quick",
            "sh scripts/nonexistent.sh --fast",
            str(tmp_path),
        )
        assert result.status == "invalid"
        assert "nonexistent.sh" in result.detail

    def test_npm_without_package_json_invalid(self, tmp_path: Path) -> None:
        result = _validate_test_command(
            "e2e", "npm run test:e2e", str(tmp_path)
        )
        assert result.status == "invalid"
        assert "package.json" in result.detail

    def test_cd_to_existing_directory_then_npm(self, tmp_path: Path) -> None:
        web_dir = tmp_path / "app/web"
        web_dir.mkdir(parents=True)
        (web_dir / "package.json").write_text('{"name":"web"}\n')
        result = _validate_test_command(
            "quick",
            "cd app/web && npm test",
            str(tmp_path),
        )
        assert result.status == "valid", result.detail

    def test_cd_to_missing_directory_invalid(self, tmp_path: Path) -> None:
        result = _validate_test_command(
            "full",
            "cd nonexistent && npm test",
            str(tmp_path),
        )
        assert result.status == "invalid"
        assert "nonexistent" in result.detail

    def test_python_dash_m_is_valid_when_interpreter_on_path(
        self, tmp_path: Path
    ) -> None:
        result = _validate_test_command(
            "quick",
            "python3 -m pytest -q",
            str(tmp_path),
        )
        assert result.status == "valid", result.detail

    def test_setup_venv_bootstrap_allows_synthetic_python(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "app/scripts").mkdir(parents=True)
        setup = tmp_path / "app/scripts/setup-venv.sh"
        _make_script(setup)
        result = _validate_test_command(
            "full",
            "sh app/scripts/setup-venv.sh && app/.venv/bin/python3 -m pytest yoke",
            str(tmp_path),
        )
        assert result.status == "valid", result.detail

    def test_semicolon_chained_commands_tracked(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg/package.json").write_text('{"name":"pkg"}\n')
        result = _validate_test_command(
            "full",
            "cd pkg ; npm run lint ; npm test",
            str(tmp_path),
        )
        assert result.status == "valid", result.detail

    def test_invalid_detail_mentions_missing_script(self, tmp_path: Path) -> None:
        result = _validate_test_command(
            "quick",
            "sh scripts/does-not-exist.sh",
            str(tmp_path),
        )
        assert result.status == "invalid"
        assert "does-not-exist.sh" in result.detail


# ---------------------------------------------------------------------------
# Output format contract
# ---------------------------------------------------------------------------


class TestFormatContract:
    def test_valid_lines_preserve_empty_detail_suffix(self) -> None:
        results = [
            TestCommandResult("quick", "valid", ""),
            TestCommandResult("full", "valid", ""),
            TestCommandResult("e2e", "valid", ""),
            TestCommandResult("smoke", "valid", ""),
        ]
        block = format_validation_block("alpha", results)
        lines = block.splitlines()
        assert lines[0] == "project=alpha"
        assert lines[1] == "quick=valid|"
        assert lines[2] == "full=valid|"
        assert lines[3] == "e2e=valid|"
        assert lines[4] == "smoke=valid|"

    def test_canonical_scope_order(self) -> None:
        """``validate_project_test_commands`` is responsible for canonical
        order; ``format_validation_block`` emits whatever the caller passes."""
        results = [
            TestCommandResult("quick", "empty", ""),
            TestCommandResult("full", "empty", ""),
            TestCommandResult("e2e", "empty", ""),
            TestCommandResult("smoke", "empty", ""),
        ]
        block = format_validation_block("alpha", results)
        fields = [line.split("=", 1)[0] for line in block.splitlines()[1:]]
        assert fields == ["quick", "full", "e2e", "smoke"]

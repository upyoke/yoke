"""Tests for stale_string_audit.py."""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest import mock

import pytest

from yoke_core.domain.stale_string_audit import (
    DEFAULT_TEST_DIRS,
    _extract_dirs_from_test_command,
    _looks_like_test_surface,
    _python_grep,
    _scan_test_directories,
    discover_test_surfaces,
    grep_surfaces,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def temp_project():
    """Create a temporary project layout with test directories and files."""
    with tempfile.TemporaryDirectory() as d:
        # Create test directories
        e2e = os.path.join(d, "e2e")
        helpers = os.path.join(d, "e2e", "helpers")
        tests = os.path.join(d, "__tests__")
        os.makedirs(helpers)
        os.makedirs(tests)

        # Create test files with known strings
        with open(os.path.join(e2e, "auth.spec.ts"), "w") as f:
            f.write('test("login button", () => {\n')
            f.write('  const btn = page.getByText("Drop a Log & Enter");\n')
            f.write("});\n")

        with open(os.path.join(helpers, "api-mocks.ts"), "w") as f:
            f.write("export function loginViaUI() {\n")
            f.write('  return page.click("Drop a Log & Enter");\n')
            f.write("}\n")

        with open(os.path.join(e2e, "smoke.spec.ts"), "w") as f:
            f.write('test("smoke test", () => {\n')
            f.write('  expect(title).toBe("POOP Theme Login");\n')
            f.write("});\n")

        with open(os.path.join(tests, "unit.test.ts"), "w") as f:
            f.write("describe('utils', () => {\n")
            f.write("  it('formats correctly', () => {});\n")
            f.write("});\n")

        # Non-test file that should not be matched by extension filter
        with open(os.path.join(e2e, "config.json"), "w") as f:
            f.write('{"theme": "Drop a Log & Enter"}\n')

        yield d


# ── grep_surfaces tests ─────────────────────────────────────────────────


def test_grep_finds_string_in_spec_files(temp_project):
    matches = grep_surfaces(
        temp_project,
        ["Drop a Log & Enter"],
        ["e2e/"],
    )
    assert len(matches) >= 2
    files = {m["file"] for m in matches}
    assert "e2e/auth.spec.ts" in files
    assert "e2e/helpers/api-mocks.ts" in files


def test_grep_finds_string_in_helpers(temp_project):
    """The gate covers helper surfaces."""
    matches = grep_surfaces(
        temp_project,
        ["loginViaUI"],
        ["e2e/"],
    )
    assert any(m["file"] == "e2e/helpers/api-mocks.ts" for m in matches)


def test_grep_finds_string_in_smoke_files(temp_project):
    """The gate covers smoke-only surfaces."""
    matches = grep_surfaces(
        temp_project,
        ["POOP Theme"],
        ["e2e/"],
    )
    assert any(m["file"] == "e2e/smoke.spec.ts" for m in matches)


def test_grep_no_matches_returns_empty(temp_project):
    matches = grep_surfaces(
        temp_project,
        ["nonexistent string xyz"],
        ["e2e/"],
    )
    assert matches == []


def test_grep_multiple_surfaces(temp_project):
    matches = grep_surfaces(
        temp_project,
        ["Drop a Log & Enter"],
        ["e2e/", "__tests__/"],
    )
    # Should find in e2e but not in __tests__
    assert len(matches) >= 2
    assert all("e2e/" in m["file"] for m in matches)


def test_grep_multiple_strings(temp_project):
    matches = grep_surfaces(
        temp_project,
        ["Drop a Log & Enter", "POOP Theme"],
        ["e2e/"],
    )
    strings_found = {m["string"] for m in matches}
    assert "Drop a Log & Enter" in strings_found
    assert "POOP Theme" in strings_found


def test_grep_ignores_non_code_files(temp_project):
    """config.json has the string but .json is not in TEST_FILE_GLOBS."""
    matches = grep_surfaces(
        temp_project,
        ["Drop a Log & Enter"],
        ["e2e/"],
    )
    assert not any(m["file"].endswith(".json") for m in matches)


def test_grep_empty_strings_returns_empty(temp_project):
    matches = grep_surfaces(temp_project, [], ["e2e/"])
    assert matches == []


def test_grep_empty_surfaces_returns_empty(temp_project):
    matches = grep_surfaces(temp_project, ["Drop a Log & Enter"], [])
    assert matches == []


def test_grep_nonexistent_surface_returns_empty(temp_project):
    matches = grep_surfaces(
        temp_project,
        ["Drop a Log & Enter"],
        ["nonexistent_dir/"],
    )
    assert matches == []


# ── _python_grep tests (fallback) ──────────────────────────────────────


def test_python_grep_finds_matches(temp_project):
    matches = _python_grep(temp_project, "Drop a Log & Enter", "e2e/")
    assert len(matches) >= 2


def test_python_grep_respects_extensions(temp_project):
    """Only .ts/.tsx/.js/.jsx/.py files should be searched."""
    matches = _python_grep(temp_project, "Drop a Log & Enter", "e2e/")
    assert not any(m["file"].endswith(".json") for m in matches)


@pytest.mark.parametrize("backend", ["_run_rg", "_python_grep"])
@pytest.mark.parametrize("heading", ["MACHINE", "VERSION"])
def test_single_word_heading_matches_literal_and_not_identifier(
    tmp_path, backend, heading
):
    from yoke_core.domain import stale_string_audit_grep

    if backend == "_run_rg" and shutil.which("rg") is None:
        pytest.skip(
            "Optional ripgrep backend is not installed; Python fallback is covered"
        )

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "fixture.py").write_text(
        f'heading = "{heading}"\nYOKE_{heading}_CONFIG = "supported"\n'
    )
    matches = getattr(stale_string_audit_grep, backend)(
        str(tmp_path), heading, "tests/"
    )
    assert [match["line"] for match in matches] == [1]


# ── _extract_dirs_from_test_command tests ───────────────────────────────


def test_extract_dirs_from_playwright_command():
    dirs = _extract_dirs_from_test_command("npx playwright test e2e/")
    assert "e2e/" in dirs


def test_extract_dirs_from_vitest_command():
    dirs = _extract_dirs_from_test_command("npx vitest run tests")
    assert "tests/" in dirs


def test_extract_dirs_ignores_non_test_workdir():
    dirs = _extract_dirs_from_test_command("cd app/web && npm run test:e2e")
    assert "app/web/" not in dirs


def test_extract_dirs_empty_command():
    dirs = _extract_dirs_from_test_command("")
    assert dirs == []


def test_looks_like_test_surface():
    assert _looks_like_test_surface("app/web/e2e")
    assert _looks_like_test_surface("__tests__")
    assert not _looks_like_test_surface("app/web")


# ── _scan_test_directories tests ────────────────────────────────────────


def test_scan_finds_existing_dirs(temp_project):
    found = _scan_test_directories(temp_project)
    assert "e2e/" in found
    assert "__tests__/" in found


def test_scan_skips_missing_dirs():
    with tempfile.TemporaryDirectory() as d:
        found = _scan_test_directories(d)
        assert found == []


# ── discover_test_surfaces tests ────────────────────────────────────────


def test_discover_returns_defaults_when_no_project():
    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value=None,
    ):
        result = discover_test_surfaces(9999)
    assert result["source"] == "defaults"
    assert result["surfaces"] == list(DEFAULT_TEST_DIRS)


def test_discover_uses_context_routing_testing_topic(temp_project):
    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    with (
        mock.patch(
            "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
            return_value="testproj",
        ),
        mock.patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Conn(),
        ),
        mock.patch(
            "yoke_core.domain.project_checkout_locations.checkout_for_project",
            return_value=temp_project,
        ),
        mock.patch(
            "yoke_core.domain.context_routing.get_topic_docs",
            return_value=["docs/TESTING.md"],
        ),
        mock.patch(
            "yoke_core.domain.qa_command_plans.get_registered_command",
            return_value=None,
        ),
    ):
        result = discover_test_surfaces(1)
    # Should find e2e/ and __tests__/ via directory scan fallback
    assert "e2e/" in result["surfaces"]
    assert "__tests__/" in result["surfaces"]


# build_audit_summary + CLI tests live in test_stale_string_audit_summary_cli.py.

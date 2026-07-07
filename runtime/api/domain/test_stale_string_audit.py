"""Tests for stale_string_audit.py."""

from __future__ import annotations

import os
import subprocess
import tempfile
from unittest import mock

import pytest

from yoke_core.domain.stale_string_audit import (
    DEFAULT_TEST_DIRS,
    _extract_dirs_from_test_command,
    _looks_like_test_surface,
    _normalize_candidate_string,
    _python_grep,
    _scan_test_directories,
    discover_test_surfaces,
    extract_candidate_strings,
    extract_candidate_strings_from_git_diff,
    grep_surfaces,
    is_text_sensitive_item,
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
    """Validates AC-6: gate covers helper surfaces."""
    matches = grep_surfaces(
        temp_project,
        ["loginViaUI"],
        ["e2e/"],
    )
    assert any(m["file"] == "e2e/helpers/api-mocks.ts" for m in matches)


def test_grep_finds_string_in_smoke_files(temp_project):
    """Validates AC-6: gate covers smoke-only surfaces."""
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

    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value="testproj",
    ), mock.patch(
        "yoke_core.domain.db_helpers.connect",
        return_value=_Conn(),
    ), mock.patch(
        "yoke_core.domain.project_checkout_locations.checkout_for_project",
        return_value=temp_project,
    ), mock.patch(
        "yoke_core.domain.context_routing.get_topic_docs",
        return_value=["docs/TESTING.md"],
    ), mock.patch(
        "yoke_core.domain.command_definitions.get_command",
        return_value=None,
    ):
        result = discover_test_surfaces(1)
    # Should find e2e/ and __tests__/ via directory scan fallback
    assert "e2e/" in result["surfaces"]
    assert "__tests__/" in result["surfaces"]


def test_normalize_candidate_string_filters_paths_and_commands():
    assert _normalize_candidate_string("Drop a Log & Enter") == "Drop a Log & Enter"
    assert _normalize_candidate_string("smoke.spec.ts") is None
    assert _normalize_candidate_string("python3 -m yoke_core.domain.foo") is None


def test_normalize_candidate_string_rejects_route_paths():
    """Issue 5: URL route paths are structural references, not copy."""
    assert _normalize_candidate_string("/login") is None
    assert _normalize_candidate_string("/forgot-password") is None
    assert _normalize_candidate_string("/api/v1/users") is None
    # Non-route paths with slashes are also rejected
    assert _normalize_candidate_string("src/components/foo") is None


def test_extract_candidate_strings_uses_spec_and_filters_noise():
    with mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "spec": '\n'.join([
                'Replace "Drop a Log & Enter" everywhere.',
                'Ignore `smoke.spec.ts` and `python3 -m yoke_core.domain.foo`.',
                'The button title is "RACING".',
            ]),
            "body": "",
        }.get(field, ""),
    ):
        candidates = extract_candidate_strings(1)
    assert candidates == ["Drop a Log & Enter", "RACING"]


def test_extract_candidate_strings_from_git_diff(monkeypatch):
    diff_output = '\n'.join([
        'diff --git a/foo.ts b/foo.ts',
        '-const button = "Drop a Log & Enter";',
        '-const theme = "RACING";',
        '-const file = "smoke.spec.ts";',
        '',
    ])

    monkeypatch.setattr(
        "yoke_core.domain.stale_string_audit_extract.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, diff_output, ""),
    )

    candidates = extract_candidate_strings_from_git_diff("/tmp/project")
    assert candidates == ["Drop a Log & Enter", "RACING"]


def test_is_text_sensitive_item_detects_theme_and_labels():
    with mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "title": "Theme work",
            "spec": "Touches theme strings and button labels.",
            "body": "",
        }.get(field, ""),
    ):
        assert is_text_sensitive_item(1) is True


# build_audit_summary + CLI tests live in test_stale_string_audit_summary_cli.py.

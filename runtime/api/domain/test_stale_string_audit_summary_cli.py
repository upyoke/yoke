"""build_audit_summary + CLI tests for stale_string_audit.

Sibling to test_stale_string_audit.py which holds the lower-level
grep/discover/extract helper coverage. The temp_project fixture is
duplicated here rather than promoted to a directory-wide conftest because
it is scoped to this single audit module.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from unittest import mock

import pytest

from yoke_core.domain.stale_string_audit import (
    build_audit_summary,
    main,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def temp_project():
    """Create a temporary project layout with test directories and files."""
    with tempfile.TemporaryDirectory() as d:
        e2e = os.path.join(d, "e2e")
        helpers = os.path.join(d, "e2e", "helpers")
        tests = os.path.join(d, "__tests__")
        os.makedirs(helpers)
        os.makedirs(tests)

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

        with open(os.path.join(e2e, "config.json"), "w") as f:
            f.write('{"theme": "Drop a Log & Enter"}\n')

        yield d


# ── build_audit_summary tests ──────────────────────────────────────────


def test_build_audit_summary_reports_matches(temp_project):
    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "title": "Theme refresh",
            "spec": 'Replace "Drop a Log & Enter" in the login flow.',
            "body": "",
        }.get(field, ""),
    ):
        summary = build_audit_summary(1, temp_project)
    assert summary["verdict"] == "matches_found"
    assert summary["candidate_strings"] == ["Drop a Log & Enter"]
    assert any(match["file"] == "e2e/auth.spec.ts" for match in summary["matches"])


def test_build_audit_summary_filters_new_strings_from_added_lines(temp_project):
    """Issue 6: strings in git diff added lines are not stale."""
    diff_output = '\n'.join([
        'diff --git a/e2e/auth.spec.ts b/e2e/auth.spec.ts',
        '+const heading = "Drop a Log & Enter";',
        '',
    ])

    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "title": "Theme refresh",
            "spec": 'Replace "Drop a Log & Enter" in the login flow.',
            "body": "",
        }.get(field, ""),
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_extract.subprocess.run",
        return_value=subprocess.CompletedProcess(
            ["git"], 0, diff_output, ""
        ),
    ):
        summary = build_audit_summary(1, temp_project)
    assert summary["verdict"] == "clean", (
        f"Expected clean verdict (new-string filter), got {summary['verdict']} "
        f"with matches: {summary['matches']}"
    )


def test_build_audit_summary_prefers_diff_removed_over_spec_for_theme_swap(temp_project):
    """spec-based extraction can't tell old from new values —
    when a diff shows removals, those are the authoritative old strings.

    Regression: a theme swap spec mentioning both the old string
    ("Drop a Log & Enter") and the new string ("POOP Theme") would
    previously extract both and flag the new string as stale when it
    appeared in tests. Now, the audit pulls the old string from the
    diff's ``-`` lines, ignoring the spec's mixed signal.
    """
    with open(os.path.join(temp_project, "e2e", "auth.spec.ts"), "w") as f:
        f.write('test("login button", () => {\n')
        f.write('  const btn = page.getByText("POOP Theme");\n')
        f.write("});\n")
    with open(os.path.join(temp_project, "e2e", "helpers", "api-mocks.ts"), "w") as f:
        f.write("export function loginViaUI() {\n")
        f.write('  return page.click("POOP Theme");\n')
        f.write("}\n")

    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "title": "Theme refresh",
            "spec": (
                'Replace "Drop a Log & Enter" with "POOP Theme" '
                'in the login flow.'
            ),
            "body": "",
        }.get(field, ""),
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_summary._collect_diff_strings",
        return_value=({"POOP Theme"}, {"Drop a Log & Enter"}),
    ):
        summary = build_audit_summary(1, temp_project)

    assert summary["candidate_source"] == "git_diff_removed"
    assert summary["candidate_strings"] == ["Drop a Log & Enter"]
    assert summary["verdict"] == "clean", (
        f"new string should not be flagged as stale, got {summary}"
    )


def test_build_audit_summary_diff_removed_still_flags_lingering_old_strings(temp_project):
    """Diff-derived old strings still block when they remain in test files.

    The temp_project fixture leaves ``"Drop a Log & Enter"`` in
    ``e2e/auth.spec.ts`` — simulating an incomplete theme swap where
    production code was updated but tests weren't fully converted.
    """
    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "title": "Theme refresh",
            "spec": "Swap the theme copy.",
            "body": "",
        }.get(field, ""),
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_summary._collect_diff_strings",
        return_value=({"POOP Theme"}, {"Drop a Log & Enter"}),
    ):
        summary = build_audit_summary(1, temp_project)

    assert summary["candidate_source"] == "git_diff_removed"
    assert summary["verdict"] == "matches_found"
    assert any(
        m["string"] == "Drop a Log & Enter" for m in summary["matches"]
    )


def test_build_audit_summary_blocks_text_sensitive_items_without_candidates(temp_project):
    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "title": "Theme refresh",
            "spec": "Touches theme strings but does not quote the old values.",
            "body": "",
        }.get(field, ""),
    ):
        summary = build_audit_summary(1, temp_project)
    assert summary["verdict"] == "missing_candidate_strings"


# ── CLI tests ───────────────────────────────────────────────────────────


def test_cli_grep_no_matches(temp_project):
    exit_code = main([
        "grep", temp_project,
        "--strings", "nonexistent string",
        "--surfaces", "e2e/",
    ])
    assert exit_code == 0


def test_cli_grep_with_matches(temp_project):
    exit_code = main([
        "grep", temp_project,
        "--strings", "Drop a Log & Enter",
        "--surfaces", "e2e/",
    ])
    assert exit_code == 1  # Matches found — blocking


def test_cli_grep_invalid_root():
    exit_code = main([
        "grep", "/nonexistent/path",
        "--strings", "foo",
        "--surfaces", "e2e/",
    ])
    assert exit_code == 2


def test_cli_no_command():
    exit_code = main([])
    assert exit_code == 2


def test_cli_discover_invalid_item():
    exit_code = main(["discover-surfaces", "invalid"])
    assert exit_code == 2


def test_cli_verify_blocks_when_matches_found(temp_project):
    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "title": "Theme refresh",
            "spec": 'Replace "Drop a Log & Enter" in the login flow.',
            "body": "",
        }.get(field, ""),
    ):
        exit_code = main(["verify", "1", temp_project])
    assert exit_code == 1


def test_cli_verify_errors_when_candidates_missing(temp_project):
    with mock.patch(
        "yoke_core.domain.stale_string_audit_discover._get_project_for_item",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.stale_string_audit_extract._get_item_field",
        side_effect=lambda item_id, field: {
            "title": "Theme refresh",
            "spec": "Touches theme strings without quoted old values.",
            "body": "",
        }.get(field, ""),
    ):
        exit_code = main(["verify", "1", temp_project])
    assert exit_code == 2

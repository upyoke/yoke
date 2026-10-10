"""Candidate strings and text sensitivity used by stale-string audits."""

import subprocess
from unittest import mock

from yoke_core.domain.stale_string_audit import (
    _normalize_candidate_string,
    extract_candidate_strings,
    extract_candidate_strings_from_git_diff,
    is_text_sensitive_item,
)


def test_normalize_candidate_string_filters_paths_and_commands():
    assert _normalize_candidate_string("Drop a Log & Enter") == "Drop a Log & Enter"
    assert _normalize_candidate_string("smoke.spec.ts") is None
    assert _normalize_candidate_string("python3 -m yoke_core.domain.foo") is None
    assert all(
        _normalize_candidate_string(s) is None
        for s in (
            "PYTHONPATH",
            ".remove",
            ".split",
            ".agents",
            ", or",
            ") else",
            "all Y",
        )
    )
    assert _normalize_candidate_string("RACING") == "RACING"


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
            "spec": "\n".join(
                [
                    'Replace "Drop a Log & Enter" everywhere.',
                    "Ignore `smoke.spec.ts` and `python3 -m yoke_core.domain.foo`.",
                    'The button title is "RACING".',
                ]
            ),
            "body": "",
        }.get(field, ""),
    ):
        candidates = extract_candidate_strings(1)
    assert candidates == ["Drop a Log & Enter", "RACING"]


def test_extract_candidate_strings_from_git_diff(monkeypatch):
    diff_output = "\n".join(
        [
            "diff --git a/foo.ts b/foo.ts",
            '-const button = "Drop a Log & Enter";',
            '-const theme = "RACING";',
            '-const file = "smoke.spec.ts";',
            "",
        ]
    )

    monkeypatch.setattr(
        "yoke_core.domain.stale_string_audit_extract.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, diff_output, ""
        ),
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

"""CLI contract for bounded immutable release-tag allocation."""

from __future__ import annotations

from unittest.mock import patch

from yoke_cli.commands.adapters import github_release


def test_commit_tag_allows_bounded_repository_access() -> None:
    source_sha = "a" * 40

    with patch.object(github_release, "dispatch_and_emit", return_value=0) as dispatch:
        result = github_release.github_release_create_commit_tag(
            [
                "upyoke/yoke",
                source_sha,
                "--summary",
                "Hosted release.",
                "--project",
                "yoke",
            ]
        )

    assert result == 0
    assert dispatch.call_args.kwargs["timeout_s"] == (
        github_release.RELEASE_TAG_REQUEST_TIMEOUT_SECONDS
    )
    assert dispatch.call_args.kwargs["payload"]["source_sha"] == source_sha


def test_commit_tag_adapter_dispatches_the_commit_api():
    with patch.object(github_release, "dispatch_and_emit", return_value=0) as dispatch:
        result = github_release.github_release_create_commit_tag(
            ["upyoke/yoke", "a" * 40, "--summary", "Release.", "--project", "yoke"]
        )
    assert result == 0
    assert (
        dispatch.call_args.kwargs["function_id"] == "github.release.create_commit_tag"
    )

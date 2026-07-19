"""CLI contract for bounded immutable release-tag allocation."""

from __future__ import annotations

from unittest.mock import patch

from yoke_cli.commands.adapters import github_release


def test_release_tag_allocation_allows_the_server_to_batch_a_large_history() -> None:
    source_sha = "a" * 40

    with patch.object(github_release, "dispatch_and_emit", return_value=0) as dispatch:
        result = github_release.github_release_create_next_tag(
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

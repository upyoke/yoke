"""CLI dispatch coverage for cross-repository GitHub issue migration."""

from unittest.mock import patch

from runtime.api.backlog_github_sync_test_helpers import GH_PATCH
from runtime.api.test_constants import TEST_ITEM_REF
from yoke_core.domain import backlog_github_sync


def test_migrate_issue_dispatches_canonical_item_ref():
    with (
        patch(
            "yoke_core.domain.backlog_github_sync_cli._guard_or_print",
            return_value=0,
        ),
        patch(f"{GH_PATCH}.migrate_issue_to_repo", return_value=0) as migrate,
    ):
        rc = backlog_github_sync.main(
            [
                "migrate-issue",
                TEST_ITEM_REF,
                "100",
                "org/yoke",
                "yoke",
                "org/externalwebapp",
                "externalwebapp",
            ]
        )

    assert rc == 0
    migrate.assert_called_once_with(
        TEST_ITEM_REF,
        "100",
        "org/yoke",
        "yoke",
        "org/externalwebapp",
        "externalwebapp",
    )

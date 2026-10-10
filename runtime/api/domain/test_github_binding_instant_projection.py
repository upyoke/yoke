"""GitHub binding clock projections preserve native precision and unknowns."""

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.project_github_binding_payload import (
    binding_payload,
    installation_payload,
)


@pytest.mark.parametrize(
    "clock", [None, parse_instant("1970-01-01T05:29:59.123456+05:30")]
)
def test_binding_and_installation_emit_canonical_nullable_clocks(clock):
    row = dict.fromkeys(
        (
            "installation_id",
            "repository_id",
            "api_url",
            "github_repo",
            "default_branch",
            "status",
            "last_error",
            "last_sync_outcome",
            "last_sync_error",
            "account_id",
            "account_login",
            "account_type",
            "repository_selection",
        ),
        "opaque timestamp-like 2026-10-08T12:34:56Z",
    )
    row.update(
        project_id=7, permissions="{}", last_verified_at=clock, last_sync_at=clock
    )
    expected = "1969-12-31T23:59:59.123456Z" if clock is not None else None
    binding = binding_payload(row)
    installation = installation_payload(row)
    assert binding["last_sync_at"] == expected
    assert binding["last_verified_at"] == installation["last_verified_at"] == expected
    assert binding["repository_id"] == row["repository_id"]
    assert installation["account_id"] == row["account_id"]

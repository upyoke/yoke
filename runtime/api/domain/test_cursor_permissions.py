"""Cursor permission/network regions: origin resolution and the merge pass.

Covers the two halves separately: which origins a machine's config yields,
and how the install pass unions its regions into Cursor's config files
without disturbing operator entries.
"""

from __future__ import annotations

import json

import pytest

from yoke_cli.project_install.cursor_permissions import (
    apply_cursor_permissions,
    preview_cursor_permissions,
    remove_cursor_permissions,
)
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.cursor_permissions import (
    CURSOR_CLI_ALLOW,
    CURSOR_CONFIG_RELS,
    CURSOR_CLI_REL,
    CURSOR_SANDBOX_REL,
    NETWORK_POLICY_DEFAULT,
    control_plane_origins,
    managed_cursor_regions,
)

CONFIG = {
    "connections": {
        "prod": {
            "transport": "https",
            "api_url": "https://control.example.test/api/orgs/acme",
        },
        "stage": {
            "transport": "https",
            "api_url": "https://stage.example.test/api/orgs/acme-stage",
        },
        "local": {"transport": "local-postgres"},
    },
    "github": {
        "api_url": "https://api.github.test",
        "web_url": "https://github.test",
    },
}


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _read(repo, rel) -> dict:
    return json.loads((repo / rel).read_text(encoding="utf-8"))


def test_origins_come_from_configured_endpoints_only() -> None:
    assert control_plane_origins(CONFIG) == [
        "api.github.test",
        "control.example.test",
        "github.test",
        "stage.example.test",
    ]


def test_origins_skip_non_https_transports() -> None:
    config = {"connections": {"local": {"transport": "local-postgres"}}}
    assert control_plane_origins(config) == []


def test_origins_tolerate_a_missing_or_malformed_config() -> None:
    assert control_plane_origins({}) == []
    assert control_plane_origins({"connections": "not-a-mapping"}) == []
    assert control_plane_origins({"connections": {"a": {"transport": "https"}}}) == []


def test_managed_regions_pair_entries_with_the_network_default() -> None:
    regions = managed_cursor_regions(CONFIG)
    assert regions[CURSOR_CLI_REL]["entries"] == list(CURSOR_CLI_ALLOW)
    assert regions[CURSOR_SANDBOX_REL]["default"] == NETWORK_POLICY_DEFAULT
    assert "control.example.test" in regions[CURSOR_SANDBOX_REL]["entries"]


def test_apply_creates_both_regions(repo) -> None:
    records, report = apply_cursor_permissions(repo, config=CONFIG)

    assert report["changed"] is True
    cli = _read(repo, CURSOR_CLI_REL)
    assert cli["permissions"]["allow"] == list(CURSOR_CLI_ALLOW)
    sandbox = _read(repo, CURSOR_SANDBOX_REL)
    assert sandbox["networkPolicy"]["default"] == NETWORK_POLICY_DEFAULT
    assert "control.example.test" in sandbox["networkPolicy"]["allow"]
    assert set(records) == set(CURSOR_CONFIG_RELS)


def test_a_created_cli_file_carries_the_schema_version(repo) -> None:
    apply_cursor_permissions(repo, config=CONFIG)

    assert _read(repo, CURSOR_CLI_REL)["version"] == 1


def test_reapply_is_idempotent(repo) -> None:
    apply_cursor_permissions(repo, config=CONFIG)
    before = (repo / CURSOR_CLI_REL).read_text(encoding="utf-8")

    _records, report = apply_cursor_permissions(repo, config=CONFIG)

    assert report["changed"] is False
    assert (repo / CURSOR_CLI_REL).read_text(encoding="utf-8") == before


def test_operator_entries_survive_and_keep_their_order(repo) -> None:
    (repo / ".cursor").mkdir()
    (repo / CURSOR_CLI_REL).write_text(
        json.dumps({"permissions": {"allow": ["Shell(make *)"], "deny": ["Shell(rm *)"]}}),
        encoding="utf-8",
    )

    apply_cursor_permissions(repo, config=CONFIG)

    cli = _read(repo, CURSOR_CLI_REL)
    assert cli["permissions"]["allow"][0] == "Shell(make *)"
    assert cli["permissions"]["allow"][1:] == list(CURSOR_CLI_ALLOW)
    assert cli["permissions"]["deny"] == ["Shell(rm *)"]


def test_an_operator_network_default_is_never_overwritten(repo) -> None:
    (repo / ".cursor").mkdir()
    (repo / CURSOR_SANDBOX_REL).write_text(
        json.dumps({"networkPolicy": {"default": "allow"}}), encoding="utf-8",
    )

    records, _report = apply_cursor_permissions(repo, config=CONFIG)

    assert _read(repo, CURSOR_SANDBOX_REL)["networkPolicy"]["default"] == "allow"
    assert records[CURSOR_SANDBOX_REL]["set_default"] is False


def test_preview_plans_without_writing(repo) -> None:
    preview = preview_cursor_permissions(repo, config=CONFIG)

    assert preview["would_change"] is True
    assert not (repo / CURSOR_CLI_REL).exists()


def test_remove_takes_back_exactly_what_apply_added(repo) -> None:
    (repo / ".cursor").mkdir()
    (repo / CURSOR_CLI_REL).write_text(
        json.dumps({"permissions": {"allow": ["Shell(make *)"]}}), encoding="utf-8",
    )
    records, _report = apply_cursor_permissions(repo, config=CONFIG)

    removed = remove_cursor_permissions(repo, records)

    assert _read(repo, CURSOR_CLI_REL)["permissions"]["allow"] == ["Shell(make *)"]
    assert removed["removed_entries"][CURSOR_CLI_REL] == list(CURSOR_CLI_ALLOW)
    # The operator authored cli.json, so only the file this pass created goes.
    assert removed["deleted_files"] == [CURSOR_SANDBOX_REL]


def test_remove_deletes_only_files_this_pass_created(repo) -> None:
    records, _report = apply_cursor_permissions(repo, config=CONFIG)

    removed = remove_cursor_permissions(repo, records)

    assert sorted(removed["deleted_files"]) == sorted(CURSOR_CONFIG_RELS)
    assert not (repo / ".cursor").exists()


def test_invalid_json_names_the_repair(repo) -> None:
    (repo / ".cursor").mkdir()
    (repo / CURSOR_CLI_REL).write_text("{not json", encoding="utf-8")

    with pytest.raises(ProjectInstallError, match="not valid JSON"):
        apply_cursor_permissions(repo, config=CONFIG)

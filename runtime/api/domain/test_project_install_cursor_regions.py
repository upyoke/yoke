"""Cursor permission/network regions across the full install wiring.

The regions resolve from the installing machine's config rather than the
bundle, so these exercise ``apply_bundle`` / ``uninstall`` end to end and
assert the manifest lineage that makes uninstall precise.
"""

from __future__ import annotations

import json

import pytest

from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_safe_bundle_paths,
)
from yoke_contracts.cursor_permissions import (
    CURSOR_CLI_ALLOW,
    CURSOR_CLI_REL,
    CURSOR_PERMISSIONS_MANIFEST_KEY,
    CURSOR_SANDBOX_REL,
)
from yoke_core.domain import project_install
from yoke_core.domain.project_install import apply_bundle
from yoke_core.domain.project_install_test_helpers import make_bundle

MANIFEST_REL = ".yoke/install-manifest.json"

CONFIGURED_ORIGIN = "control.example.test"


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    """Isolated machine config declaring one https control plane."""
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    (home / "config.json").write_text(
        json.dumps(
            {
                "connections": {
                    "prod": {
                        "transport": "https",
                        "api_url": f"https://{CONFIGURED_ORIGIN}/api/orgs/acme",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return home


@pytest.fixture()
def repo(tmp_path, machine_home):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _read(repo, rel) -> dict:
    return json.loads((repo / rel).read_text(encoding="utf-8"))


def test_install_creates_both_cursor_regions(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    cli = _read(repo, CURSOR_CLI_REL)
    assert cli["permissions"]["allow"] == list(CURSOR_CLI_ALLOW)
    sandbox = _read(repo, CURSOR_SANDBOX_REL)
    assert sandbox["networkPolicy"]["default"] == "deny"
    assert sandbox["networkPolicy"]["allow"] == [CONFIGURED_ORIGIN]
    assert report["cursor_permissions_actions"]

    records = _read(repo, MANIFEST_REL)[CURSOR_PERMISSIONS_MANIFEST_KEY]
    assert records[CURSOR_CLI_REL]["created_file"] is True
    assert records[CURSOR_CLI_REL]["added_entries"] == list(CURSOR_CLI_ALLOW)


def test_refresh_leaves_the_regions_untouched(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    before = (repo / CURSOR_CLI_REL).read_text(encoding="utf-8")

    report = apply_bundle(repo, make_bundle(), operation="refresh", source="test")

    assert (repo / CURSOR_CLI_REL).read_text(encoding="utf-8") == before
    assert all(
        "Exists:" in line for line in report["cursor_permissions_actions"]
    )


def test_refresh_keeps_the_manifest_record_of_what_install_added(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    before = _read(repo, MANIFEST_REL)[CURSOR_PERMISSIONS_MANIFEST_KEY]

    apply_bundle(repo, make_bundle(), operation="refresh", source="test")

    # A refresh adds nothing new; without carry-forward the record would be
    # emptied and uninstall would stop removing what install wrote.
    assert _read(repo, MANIFEST_REL)[CURSOR_PERMISSIONS_MANIFEST_KEY] == before


def test_uninstall_after_a_refresh_still_cleans_up(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    apply_bundle(repo, make_bundle(), operation="refresh", source="test")

    project_install.uninstall(repo)

    assert not (repo / CURSOR_CLI_REL).exists()
    assert not (repo / CURSOR_SANDBOX_REL).exists()


def test_no_configured_origin_leaves_the_network_policy_unwritten(
    tmp_path, monkeypatch,
) -> None:
    home = tmp_path / "local-only-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    (home / "config.json").write_text(
        json.dumps({"connections": {"local": {"transport": "local-postgres"}}}),
        encoding="utf-8",
    )
    root = tmp_path / "local-only-repo"
    root.mkdir()

    report = apply_bundle(root, make_bundle(), source="test")

    # A deny-all policy with an empty allow list would block every host, so
    # the region stays unwritten and the skip says why.
    assert not (root / CURSOR_SANDBOX_REL).exists()
    assert (root / CURSOR_CLI_REL).is_file()
    assert any(
        "Skipped: " + CURSOR_SANDBOX_REL in line
        for line in report["cursor_permissions_actions"]
    )


def test_uninstall_preserves_an_operator_authored_config(repo) -> None:
    (repo / ".cursor").mkdir()
    (repo / CURSOR_CLI_REL).write_text(
        json.dumps({"permissions": {"allow": ["Shell(make *)"]}}), encoding="utf-8",
    )
    apply_bundle(repo, make_bundle(), source="test")

    project_install.uninstall(repo)

    assert _read(repo, CURSOR_CLI_REL)["permissions"]["allow"] == ["Shell(make *)"]
    assert not (repo / CURSOR_SANDBOX_REL).exists()


def test_uninstall_removes_regions_it_created(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")

    project_install.uninstall(repo)

    assert not (repo / CURSOR_CLI_REL).exists()
    assert not (repo / CURSOR_SANDBOX_REL).exists()


@pytest.mark.parametrize("rel", [CURSOR_CLI_REL, CURSOR_SANDBOX_REL])
def test_a_bundle_may_not_ship_a_merge_managed_file_literally(rel) -> None:
    with pytest.raises(ProjectInstallError, match="merge-managed harness"):
        assert_safe_bundle_paths([rel])

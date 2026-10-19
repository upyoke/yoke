"""Published harness CLI releases decide whether a golden is behind."""

import json

import pytest

from yoke_contracts.harness_cli_manifest import HARNESS_CLI_MANIFESTS
from yoke_contracts.harness_cli_releases import (
    HARNESS_CLI_RELEASE_BY_ID,
    HARNESS_CLI_RELEASES,
    outdated_harness_clis,
)

LATEST = {"claude-code": "2.1.300", "codex": "0.163.0", "cursor": "2026.10.16-e3cb207"}


def test_every_harness_family_has_a_release_channel():
    assert [r.harness_id for r in HARNESS_CLI_RELEASES] == [
        m.harness_id for m in HARNESS_CLI_MANIFESTS
    ]
    assert [r.surface_id for r in HARNESS_CLI_RELEASES] == [
        m.surface_id for m in HARNESS_CLI_MANIFESTS
    ]


@pytest.mark.parametrize(
    "harness_id,body,version",
    [
        ("claude-code", "2.1.300\n", "2.1.300"),
        ("codex", json.dumps({"tag_name": "rust-v0.163.0"}), "0.163.0"),
        (
            "cursor",
            'DOWNLOAD_URL="https://downloads.cursor.com/lab/2026.10.16-e3cb207/'
            '${OS}/${ARCH}/agent-cli-package.tar.gz"',
            "2026.10.16-e3cb207",
        ),
    ],
)
def test_each_channel_names_its_latest_version(harness_id, body, version):
    assert HARNESS_CLI_RELEASE_BY_ID[harness_id].latest_version(body) == version


@pytest.mark.parametrize(
    "harness_id,body",
    [
        ("claude-code", "<html>maintenance</html>"),
        ("codex", "not json"),
        ("codex", json.dumps({"tag_name": "v1"})),
        ("cursor", "echo installer moved"),
    ],
)
def test_an_unreadable_channel_refuses_by_name(harness_id, body):
    with pytest.raises(ValueError, match="harness_cli_latest_unreadable"):
        HARNESS_CLI_RELEASE_BY_ID[harness_id].latest_version(body)


def test_an_unrecorded_golden_is_behind_on_every_cli():
    assert outdated_harness_clis(None, LATEST) == ("claude-code", "codex", "cursor")


def test_a_current_golden_is_behind_on_nothing():
    assert outdated_harness_clis(dict(LATEST), LATEST) == ()


def test_only_an_older_cli_is_behind():
    recorded = {**LATEST, "codex": "0.149.1"}
    assert outdated_harness_clis(recorded, LATEST) == ("codex",)


def test_a_cursor_build_of_the_same_release_day_is_current():
    recorded = {**LATEST, "cursor": "2026.10.16-0000000"}
    assert outdated_harness_clis(recorded, LATEST) == ()


def test_a_golden_newer_than_the_channel_is_current():
    recorded = {**LATEST, "claude-code": "2.1.301"}
    assert outdated_harness_clis(recorded, LATEST) == ()

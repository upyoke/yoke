"""A hand golden capture warns when its harness CLIs are behind latest."""

import json

import pytest

from yoke_harness import golden_harness_clis
from yoke_harness import harness_cli_latest as latest_check

LATEST = {"claude-code": "2.1.300", "codex": "0.163.0", "cursor": "2026.10.16-e3cb207"}
CHANNELS = {
    "https://downloads.claude.ai/claude-code-releases/latest": "2.1.300",
    "https://releases.openai.com/codex/channels/latest": json.dumps(
        {"tag_name": "rust-v0.163.0"}
    ),
    "https://cursor.com/install": "https://downloads.cursor.com/lab/2026.10.16-e3cb207/",
}


def capture_payload(recorded):
    return {"checks": [{"name": "golden_capture", "ok": True, "harness_cli_versions": recorded}]}


def test_a_hand_capture_behind_latest_names_each_behind_cli(capsys):
    warning = latest_check.warn_capture_behind_latest(
        "golden_capture",
        {"status": "verified"},
        capture_payload({**LATEST, "codex": "0.149.1"}),
        fetch=CHANNELS.__getitem__,
    )
    assert warning.startswith("warning golden_harness_clis_behind_latest: codex 0.149.1 < 0.163.0.")
    assert "claude-code" not in warning
    assert golden_harness_clis.PROVISIONING_DOC in warning
    assert warning in capsys.readouterr().err


@pytest.mark.parametrize(
    "operation, status, recorded",
    [
        ("golden_capture", "verified", dict(LATEST)),
        ("golden_capture", "error", {"codex": "0.149.1"}),
        ("reset", "verified", {"codex": "0.149.1"}),
    ],
)
def test_a_current_failed_or_other_operation_does_not_warn(operation, status, recorded, capsys):
    assert latest_check.warn_capture_behind_latest(
        operation, {"status": status}, capture_payload(recorded), fetch=CHANNELS.__getitem__
    ) is None
    assert capsys.readouterr().err == ""


def test_an_unreachable_release_channel_warns_instead_of_failing_the_capture():
    def offline(url):
        raise OSError("network down")

    warning = latest_check.warn_capture_behind_latest(
        "golden_capture", {"status": "verified"}, capture_payload(dict(LATEST)), fetch=offline
    )
    assert warning.startswith("warning golden_harness_latest_unavailable:")
    assert "network down" in warning

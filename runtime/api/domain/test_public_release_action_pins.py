"""Immutable, Node 24-capable action pins for public release factories."""

from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_NAMES = (
    "yoke-build-artifacts.yml",
    "yoke-release.yml",
    "yoke-server-image.yml",
)
_ACTION_PINS = {
    "actions/attest": "a1948c3f048ba23858d222213b7c278aabede763",
    "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "docker/build-push-action": "53b7df96c91f9c12dcc8a07bcb9ccacbed38856a",
    "docker/login-action": "b45d80f862d83dbcd57f89517bcf500b2ab88fb2",
}
_REMOTE_USE = re.compile(r"^\s*uses:\s*([^./\s][^@\s]+)@([^\s#]+)", re.MULTILINE)


def test_public_release_actions_use_exact_reviewed_commit_pins():
    found: set[str] = set()
    workflows = _ROOT / ".github" / "workflows"
    for name in _WORKFLOW_NAMES:
        text = workflows.joinpath(name).read_text(encoding="utf-8")
        for action, revision in _REMOTE_USE.findall(text):
            assert action in _ACTION_PINS, f"unreviewed remote action: {action}"
            assert revision == _ACTION_PINS[action], (
                f"mutable or stale action revision: {action}@{revision}"
            )
            found.add(action)
    assert found == set(_ACTION_PINS)

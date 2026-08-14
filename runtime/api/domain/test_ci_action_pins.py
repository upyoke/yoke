"""Immutable action revisions for the broad CI workflows."""

from __future__ import annotations

from pathlib import Path
import re


_ROOT = Path(__file__).resolve().parents[3]
_REMOTE_USE = re.compile(
    r"^\s*uses:\s*([^./\s][^@\s]+)@([^\s#]+)",
    re.MULTILINE,
)
_EXPECTED_ACTIONS = {
    "actions/checkout",
    "actions/setup-node",
    "actions/setup-python",
    "actions/upload-artifact",
}
_WORKFLOWS = ("yoke-ci.yml", "browser-runtime-tests.yml")


def test_ci_actions_use_immutable_revisions() -> None:
    found: set[str] = set()
    for workflow in _WORKFLOWS:
        text = (_ROOT / ".github" / "workflows" / workflow).read_text(
            encoding="utf-8"
        )
        for action, revision in _REMOTE_USE.findall(text):
            assert action in _EXPECTED_ACTIONS, f"unreviewed CI action: {action}"
            assert len(revision) == 40
            assert all(character in "0123456789abcdef" for character in revision)
            found.add(action)
    assert found == _EXPECTED_ACTIONS

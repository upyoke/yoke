"""Immutable action revisions for the broad CI workflow."""

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
    "actions/setup-python",
    "actions/upload-artifact",
}


def test_ci_actions_use_immutable_revisions() -> None:
    text = (_ROOT / ".github/workflows/yoke-ci.yml").read_text(encoding="utf-8")
    found: set[str] = set()
    for action, revision in _REMOTE_USE.findall(text):
        assert action in _EXPECTED_ACTIONS, f"unreviewed CI action: {action}"
        assert len(revision) == 40
        assert all(character in "0123456789abcdef" for character in revision)
        found.add(action)
    assert found == _EXPECTED_ACTIONS

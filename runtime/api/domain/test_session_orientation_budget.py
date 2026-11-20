"""Optional Git context must not crowd startup instructions out of a hook."""

from pathlib import Path

import pytest

from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_core.domain import python_interpreter_probe as probe
from yoke_core.domain import session_orientation as orientation


@pytest.mark.parametrize(
    "branch",
    ["main", "gh-readonly-queue/main/" + "x" * 2000],
    ids=["short-branch", "long-queue-branch"],
)
def test_long_git_metadata_preserves_the_startup_block(monkeypatch, branch):
    root = Path("/checkout")
    startup = ("Required authority and trust instructions. " * 15).rstrip()
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_startup_block_lines", lambda: ["", startup])
    monkeypatch.setattr(
        orientation,
        "_git_line",
        lambda _, args: branch if args[0] == "branch" else "abc1234 " + "長" * 1000,
    )

    rendered = orientation.render_orientation({"session_id": "test-session"}, root)

    assert startup in rendered
    assert "Your Session: test-session" in rendered
    assert f"Root: {root}" in rendered
    assert "Recent commit:" not in rendered
    assert len(rendered.encode("utf-8")) <= min(1200, min(INLINE_CONTEXT_BYTES.values()))
    assert ("Current branch:" in rendered) is (branch == "main")


def test_bound_project_orientation_is_under_twelve_hundred_bytes(monkeypatch):
    for name in ("YOKE_SESSION_LAUNCH_CONTEXT", "YOKE_HEADLESS_RESUME_ATTEMPT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda *_: "main")
    body = orientation.render_orientation({"session_id": "a" * 36}, Path("/checkout"))
    assert len(body.encode()) < 1200


def test_long_metadata_uses_the_project_orientation_budget(monkeypatch):
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda _, args:
                        "topic-" + "x" * 900 if args[0] == "branch"
                        else "a" * 1000)
    body = orientation.render_orientation({"session_id": "a" * 36}, Path("/checkout"))
    assert len(body.encode()) <= 1200


def _hand_started(monkeypatch, advisories: list[str]) -> None:
    for name in ("YOKE_SESSION_LAUNCH_CONTEXT", "YOKE_HEADLESS_RESUME_ATTEMPT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: advisories)
    monkeypatch.setattr(orientation, "_git_line", lambda _, args: (
        "feature-branch" if args[0] == "branch" else "abc1234 a recent commit"))


def test_orientation_reports_git_state(monkeypatch):
    # A fixed root and no advisories: runner temp paths never decide the test.
    _hand_started(monkeypatch, [])
    out = orientation.render_orientation({"session_id": "a" * 36}, Path("/checkout"))
    assert "Current branch: feature-branch" in out
    assert "abc1234 a recent commit" in out


def _windows_advisory(monkeypatch) -> str:
    monkeypatch.setattr(probe, "_recommended_python", lambda **_: (
        r"C:\Users\someone\AppData\Local\Programs\Python\Python313\python.exe"))
    return probe.render_advisory(probe.ProbeResult(
        ok=False, resolved_python=r"C:\Windows\py.exe",
        missing_module="pydantic", override_used=False))


@pytest.mark.parametrize("root", [
    "/Users/someone-with-a-long-name/Library/CloudStorage/OneDrive-Company/Projects/client-app",
    r"C:\Users\someone-with-a-long-name\OneDrive - Company Name\Documents\Projects\client-app",
], ids=["macos", "windows"])
@pytest.mark.parametrize("advised", [False, True], ids=["plain", "advisory"])
def test_realistic_root_keeps_git_lines(monkeypatch, root, advised):
    advisories = [_windows_advisory(monkeypatch), ""] if advised else []
    _hand_started(monkeypatch, advisories)
    body = orientation.render_orientation({"session_id": "a" * 36}, Path(root))
    assert len(root) >= 85 and "Main-session flow" in body
    assert "Current branch: feature-branch" in body
    assert "abc1234 a recent commit" in body
    assert len(body.encode()) <= min(INLINE_CONTEXT_BYTES.values())

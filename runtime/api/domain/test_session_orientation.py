"""Client-side session orientation for a managed project's main session.

The server skips the orientation policy over https because it cannot see
the client machine, and the source-repo renderer is absent from a managed
project. These regressions pin the client-side replacement: it orients the
first prompt exactly once, stays silent on everything else, never raises,
and does not duplicate a packet the managed doctrine block already carries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.project_contract.install_manifest import INSTALL_MANIFEST_REL
from yoke_contracts.project_contract.managed_block import (
    MAIN_AGENT_PACKET_MARKER,
)
from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_RECEIPT_REL,
    render_installed_layer_receipt,
)
from yoke_core.domain import session_orientation as so


def _payload(root: Path, session_id: str = "sess-abc") -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "cwd": str(root),
            "hook_event_name": "UserPromptSubmit",
        }
    )


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A minimal managed project: the .yoke dir the installer always makes."""
    (tmp_path / ".yoke").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def isolated_markers(tmp_path_factory, monkeypatch) -> None:
    """Point the fire-once markers at a per-test scratch root."""
    root = tmp_path_factory.mktemp("markers")
    monkeypatch.setattr(
        so,
        "_claim_first_prompt",
        _FirstPromptSpy(root).claim,
    )


class _FirstPromptSpy:
    """Filesystem-free stand-in with the real once-per-session semantics."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.seen: set[str] = set()

    def claim(self, session_id: str) -> bool:
        if session_id in self.seen:
            return False
        self.seen.add(session_id)
        return True


def test_first_prompt_gets_oriented(project: Path) -> None:
    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert so.ORIENTATION_HEADING in out
    assert "Your Session: sess-abc" in out
    assert str(project) in out


def test_only_the_first_prompt_of_a_session_is_oriented(project: Path) -> None:
    # Orientation is startup context, not a per-turn banner: repeating it
    # every prompt would crowd out the conversation it is meant to seed.
    first = so.orientation_for_hook("UserPromptSubmit", _payload(project))
    second = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert first is not None
    assert second is None


def test_other_hook_events_are_not_oriented(project: Path) -> None:
    for event in ("PreToolUse", "PostToolUse", "SessionStart", "Stop"):
        assert so.orientation_for_hook(event, _payload(project)) is None


def test_cwd_outside_a_managed_project_is_not_oriented(tmp_path: Path) -> None:
    # No .yoke dir: the agent is working somewhere Yoke does not manage, and
    # orienting it toward a project that is not there would be misdirection.
    assert so.orientation_for_hook("UserPromptSubmit", _payload(tmp_path)) is None


@pytest.mark.parametrize(
    "stdin_data",
    ["", "not json", "[]", "null", json.dumps({"cwd": "/tmp"})],
)
def test_unusable_payloads_degrade_to_silence(stdin_data: str) -> None:
    # A hook must never break the agent that called it, so every unusable
    # payload returns None rather than raising.
    assert so.orientation_for_hook("UserPromptSubmit", stdin_data) is None


def test_orientation_reports_git_state(project: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_git(root: Path, args: list[str]) -> str:
        calls.append(args)
        if args[:1] == ["branch"]:
            return "feature-branch"
        return "abc1234 a recent commit"

    monkeypatch.setattr(so, "_git_line", fake_git)
    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert "Current branch: feature-branch" in out
    assert "abc1234 a recent commit" in out


def test_orientation_survives_a_checkout_without_git(
    project: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(so, "_git_line", lambda root, args: "")
    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert "Current branch:" not in out
    assert "Recent commits:" not in out


def test_packet_is_delivered_when_the_rules_files_lack_it(
    project: Path,
) -> None:
    # A project installed before the packet shipped has rules files with no
    # marker; the hook is then the only thing that can supply the packet.
    (project / "AGENTS.md").write_text("# House rules\n", encoding="utf-8")

    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert "Main-session DB/API packet (main_agent)" in out


def test_packet_is_not_duplicated_when_the_block_already_carries_it(
    project: Path,
) -> None:
    # The doctrine block the install bundle composes already carries the
    # packet and the harness auto-loads it; sending a second copy would
    # spend tens of thousands of tokens to say the same thing twice.
    (project / "CLAUDE.md").write_text(
        f"# House rules\n\n{MAIN_AGENT_PACKET_MARKER}\nMain-session DB/API "
        "packet (main_agent):\n",
        encoding="utf-8",
    )

    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert so.ORIENTATION_HEADING in out
    assert "Layer-explicit packet for the top-level Yoke session" not in out


def test_orientation_names_the_board_only_when_it_exists(project: Path) -> None:
    without = so.orientation_for_hook("UserPromptSubmit", _payload(project))
    assert without is not None
    assert "BOARD.md" not in without

    (project / ".yoke" / "BOARD.md").write_text("# board\n", encoding="utf-8")
    with_board = so.orientation_for_hook(
        "UserPromptSubmit", _payload(project, session_id="sess-two"),
    )
    assert with_board is not None
    assert "Board available at .yoke/BOARD.md" in with_board


def test_orientation_warns_when_installed_teaching_is_behind(
    project: Path, monkeypatch,
) -> None:
    receipt = project / INSTALLED_LAYER_RECEIPT_REL
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        render_installed_layer_receipt("0.1.1+launch.24"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version",
        lambda: "0.1.1+launch.25",
    )

    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert "operating layer 0.1.1+launch.24 is behind" in out
    assert f"`yoke project install {project}`" in out


def test_orientation_warns_for_install_predating_tracked_receipts(
    project: Path, monkeypatch,
) -> None:
    manifest = project / INSTALL_MANIFEST_REL
    manifest.write_text(
        json.dumps({"yoke_version": "0.1.1+launch.24"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version",
        lambda: "0.1.1+launch.25",
    )

    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert "operating layer 0.1.1+launch.24 is behind" in out
    assert f"`yoke project install {project}`" in out


@pytest.mark.parametrize(
    "receipt_text,running_version",
    [
        (render_installed_layer_receipt("0.1.1+launch.25"), "0.1.1+launch.25"),
        (render_installed_layer_receipt("0.1.1+launch.26"), "0.1.1+launch.25"),
        ("not json\n", "0.1.1+launch.25"),
    ],
)
def test_orientation_stays_silent_without_older_comparable_teaching(
    project: Path, monkeypatch, receipt_text: str, running_version: str,
) -> None:
    receipt = project / INSTALLED_LAYER_RECEIPT_REL
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(receipt_text, encoding="utf-8")
    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version",
        lambda: running_version,
    )

    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert "operating layer" not in out


def test_module_takes_no_source_repo_imports() -> None:
    # The module runs inside a managed project's hook process, where the
    # `runtime` tree does not exist. A static import of it would turn every
    # hook event in every managed project into an ImportError.
    source = Path(so.__file__).read_text(encoding="utf-8")
    assert "runtime." not in source.replace("runtime.*", "")

"""Client-side session orientation for a managed project's main session.

The server skips the orientation policy over https because it cannot see
the client machine, and the source-repo renderer is absent from a managed
project. These regressions pin the client-side replacement: it orients each
harness on its real startup-context event exactly once, stays silent on every
other event, never raises, and carries the generated main-agent packet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.project_contract.install_manifest import INSTALL_MANIFEST_REL
from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_RECEIPT_REL,
    render_installed_layer_receipt,
)
from yoke_core.domain import session_orientation as so
from yoke_core.domain import session_orientation_delivery as delivery
from yoke_core.domain.project_scratch_roots import ENV_KEY as SCRATCH_ROOT_ENV_KEY


def _payload(root: Path, session_id: str = "sess-abc") -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "cwd": str(root),
            "hook_event_name": "UserPromptSubmit",
        }
    )


def _cursor_payload(root: Path, session_id: str = "sess-cursor") -> str:
    return json.dumps(
        {
            "hook_event_name": "sessionStart",
            "session_id": session_id,
            "conversation_id": session_id,
            "workspace_roots": [str(root)],
        }
    )


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A minimal managed project: the .yoke dir the installer always makes."""
    (tmp_path / ".yoke").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def isolated_markers(tmp_path_factory, monkeypatch) -> None:
    """Point the attempt/delivery markers at a per-test scratch root."""
    monkeypatch.setenv(
        SCRATCH_ROOT_ENV_KEY,
        str(tmp_path_factory.mktemp("markers")),
    )
    monkeypatch.setattr(delivery, "_composed_session", None)


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
    so.confirm_orientation_delivery()
    second = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert first is not None
    assert second is None


def test_other_hook_events_are_not_oriented(project: Path) -> None:
    for event in ("PreToolUse", "PostToolUse", "SessionStart", "Stop"):
        assert so.orientation_for_hook(event, _payload(project)) is None


def test_cursor_session_start_gets_shared_orientation_without_cwd(
    project: Path,
) -> None:
    out = so.orientation_for_hook(
        "SessionStart",
        _cursor_payload(project),
        cursor=True,
    )

    assert out is not None
    assert so.ORIENTATION_HEADING in out
    assert "Your Session: sess-cursor" in out
    assert str(project) in out


def test_cursor_prompt_submit_stays_silent(project: Path) -> None:
    assert (
        so.orientation_for_hook(
            "UserPromptSubmit",
            _payload(project),
            cursor=True,
        )
        is None
    )


def test_cursor_session_start_carries_every_shared_machine_advisory(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_core.domain import main_agent_packet

    monkeypatch.setattr(
        so,
        "_operating_layer_advisory",
        lambda _root: "layer advisory",
    )
    monkeypatch.setattr(
        main_agent_packet,
        "render_interpreter_advisory_block",
        lambda: "interpreter advisory",
    )
    monkeypatch.setattr(
        main_agent_packet,
        "render_install_advisory_block",
        lambda: "install advisory",
    )

    out = so.orientation_for_hook(
        "SessionStart",
        _cursor_payload(project),
        cursor=True,
    )

    assert out is not None
    assert "layer advisory" in out
    assert "interpreter advisory" in out
    assert "install advisory" in out


def test_cursor_session_start_carries_generated_packet(project: Path) -> None:
    (project / "AGENTS.md").write_text("# House rules\n", encoding="utf-8")

    out = so.orientation_for_hook(
        "SessionStart",
        _cursor_payload(project),
        cursor=True,
    )

    assert out is not None
    assert "Main-session DB/API packet (main_agent)" in out


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
    project: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(so, "_git_line", lambda root, args: "")
    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert "Current branch:" not in out
    assert "Recent commits:" not in out


def test_packet_is_delivered_with_installed_rules(
    project: Path,
) -> None:
    # Auto-loaded rules stay compact; the hook supplies generated schema truth.
    (project / "AGENTS.md").write_text("# House rules\n", encoding="utf-8")

    out = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert out is not None
    assert "Main-session DB/API packet (main_agent)" in out


def test_orientation_names_the_board_only_when_it_exists(project: Path) -> None:
    without = so.orientation_for_hook("UserPromptSubmit", _payload(project))
    assert without is not None
    assert "BOARD.md" not in without

    so.confirm_orientation_delivery()
    (project / ".yoke" / "BOARD.md").write_text("# board\n", encoding="utf-8")
    with_board = so.orientation_for_hook(
        "UserPromptSubmit",
        _payload(project, session_id="sess-two"),
    )
    assert with_board is not None
    assert "Board available at .yoke/BOARD.md" in with_board


def test_orientation_warns_when_installed_teaching_is_behind(
    project: Path,
    monkeypatch,
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
    project: Path,
    monkeypatch,
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
    project: Path,
    monkeypatch,
    receipt_text: str,
    running_version: str,
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

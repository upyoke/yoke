"""``lint_workspace_cwd_match`` judges only the writer that actually runs.

A quoted search pattern that mentions ``pytest`` is operand data, the
call's declared workdir names where it runs, and a leading ``cd`` into
the claimed lane moves the writer there before it starts. Each case
replays a refused command from a field note; the disguised local forms
stay refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.lint_workspace_cwd_match import evaluate_payload

SESSION = "fixture-session"


@pytest.fixture
def checkouts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    lane = tmp_path / "lane"
    main = tmp_path / "main"
    lane.mkdir()
    main.mkdir()
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match.resolve_session_worktree_paths",
        lambda session_id: [str(lane)] if session_id == SESSION else [],
    )
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match._read_mode",
        lambda payload=None: "deny",
    )
    return lane, main


def _payload(command: str, cwd: Path, workdir: Path | None = None) -> dict:
    tool_input: dict = {"command": command}
    if workdir is not None:
        tool_input["workdir"] = str(workdir)
    return {
        "tool_name": "Bash",
        "tool_input": tool_input,
        "cwd": str(cwd),
        "session_id": SESSION,
    }


def test_quoted_search_pattern_is_not_a_writer(checkouts) -> None:
    _lane, main = checkouts
    command = (
        "yoke qa plan list --project yoke; "
        "rg -n 'watch|pytest|bounded' docs/source-dev-doctrine.md"
    )
    assert evaluate_payload(_payload(command, main)) is None


def test_declared_workdir_in_the_lane_wins_over_main_cwd(checkouts) -> None:
    lane, main = checkouts
    payload = _payload("python3 -m pytest -q runtime/api", main, workdir=lane)
    assert evaluate_payload(payload) is None


def test_leading_cd_into_the_lane_moves_the_writer(checkouts) -> None:
    lane, main = checkouts
    command = f"cd {lane} && python -m pytest --version"
    assert evaluate_payload(_payload(command, main)) is None


def test_heredoc_body_mentioning_pytest_is_data(checkouts) -> None:
    _lane, main = checkouts
    command = "cat > /tmp/note.txt <<'EOF'\npytest runtime/api\nEOF"
    assert evaluate_payload(_payload(command, main)) is None


def test_pytest_in_command_position_from_main_is_still_refused(checkouts) -> None:
    _lane, main = checkouts
    command = "rg -n 'pytest' docs | head -3; pytest runtime/api"
    verdict = evaluate_payload(_payload(command, main))
    assert verdict is not None
    assert verdict[2] == "denied"


def test_cd_out_of_the_lane_is_still_refused(checkouts) -> None:
    lane, main = checkouts
    command = f"cd {main} && python3 -m pytest -q"
    assert evaluate_payload(_payload(command, lane)) is not None

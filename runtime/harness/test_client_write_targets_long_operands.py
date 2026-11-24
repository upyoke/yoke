"""Data strings that cannot name a file never cost the write-target fact.

A quoted sentence is one argv token and usually contains ``.``, so the
probe treats it as a path operand. Probing it must answer quietly (no
repository of its own) rather than raise and lose the fact for every other
operand of the same command. Python 3.13's ``Path.exists`` re-raises
ENAMETOOLONG where 3.14 returns False; both must answer the same.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_contracts.hook_runner.client_facts import write_target
from yoke_harness.hooks import client_facts

pytestmark = pytest.mark.windows

SENTENCE = ("The resident answered the hook inside its budget. " * 7).strip()
assert len(SENTENCE) > 300
DEEP = "/".join(["abcdefgh"] * 150)  # short components, over 1024 in total
MULTIBYTE = "雪" * 100 + ".txt"  # one 304-byte component
ROOTED = "/" + "x" * 300 + ".md"  # ``/``-leading: a mount path on Windows
LONG_WORD = "segment." * 60  # one heredoc line with no space in it

COMMANDS = {
    "commit": (f'git commit -m "{SENTENCE}" && git status', SENTENCE),
    "feedback": (
        f"yoke feedback --to universe --evidence '{SENTENCE}'",
        SENTENCE,
    ),
    "db_read": (
        f'yoke db read "SELECT id FROM items WHERE note = \'{SENTENCE}\'"',
        None,
    ),
    "heredoc": (f"git commit -F - <<'EOF'\n{LONG_WORD}\nEOF", LONG_WORD),
    "deep": (f"cat {DEEP}", DEEP),
    "multibyte": (f"cat {MULTIBYTE}", MULTIBYTE),
    "rooted": (f"printf %s {ROOTED}", ROOTED),
    "nul": ("printf %s 'a\0b.txt'", None),
}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path.resolve() / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, timeout=10)
    return root


def _facts(repo: Path, command: str) -> dict:
    payload = {
        "session_id": "sid-long-operands",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": command},
    }
    return client_facts.collect_client_facts(
        "PreToolUse",
        payload,
        "claude-code",
        client_facts.event_chain("PreToolUse", payload),
    )


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_long_data_operand_keeps_the_whole_fact(repo, capsys, name):
    body, long_operand = COMMANDS[name]
    real = repo / "notes" / "real.txt"
    facts = _facts(repo, f"{body}\ntouch {real.as_posix()}")
    assert client_facts.FAILURE_MARKER not in capsys.readouterr().err
    assert write_target(facts, real.as_posix()) == {
        "path": str(real),
        "ignored": False,
    }
    if long_operand is not None:
        entry = write_target(facts, long_operand)
        assert entry["path"]
        if name == "rooted":
            assert Path(entry["path"]).is_absolute()
            assert entry["ignored"] is None


def test_non_ascii_ignore_answer_round_trips_through_git(repo):
    ignored = repo / "雪.txt"
    tracked = repo / "notes.txt"
    (repo / ".gitignore").write_text("雪.txt\n", encoding="utf-8")

    facts = _facts(repo, f"touch {ignored.as_posix()} {tracked.as_posix()}")

    assert write_target(facts, ignored.as_posix()) == {
        "path": str(ignored),
        "ignored": True,
    }
    assert write_target(facts, tracked.as_posix())["ignored"] is False


def test_repo_root_answers_no_repository_for_unnameable_paths(repo):
    from yoke_harness.hooks import client_write_targets as targets

    for raw in (SENTENCE, DEEP, MULTIBYTE, ROOTED):
        candidate = str(repo / raw) if not raw.startswith("/") else raw
        assert targets._repo_root(candidate) in ("", str(repo))

"""Cross-harness normalization of top-level versus child execution."""

from __future__ import annotations

from yoke_contracts.session_execution import is_subagent_execution


def test_claude_subagent_hook_marker_is_child() -> None:
    assert is_subagent_execution({"agent_type": "engineer"}, env={})
    assert is_subagent_execution({}, env={"YOKE_HOOK_AGENT_TYPE": "tester"})


def test_codex_parent_and_independent_worker_are_top_level() -> None:
    assert not is_subagent_execution(
        env={"CODEX_SESSION_ID": "parent", "CODEX_THREAD_ID": "parent"}
    )
    assert not is_subagent_execution(
        env={"CODEX_SESSION_ID": "worker", "CODEX_THREAD_ID": "worker"}
    )


def test_codex_child_thread_is_subagent() -> None:
    assert is_subagent_execution(
        env={"CODEX_SESSION_ID": "parent", "CODEX_THREAD_ID": "child"}
    )


def test_cursor_normalized_child_payload_is_subagent() -> None:
    assert is_subagent_execution(
        {"is_subagent_session": True, "subagent_session_id": "child"},
        env={},
    )
    assert is_subagent_execution(
        {"conversation_id": "child", "parent_conversation_id": "parent"},
        env={},
    )


def test_cursor_child_shell_uses_nested_transcript_evidence() -> None:
    assert is_subagent_execution(
        env={
            "CURSOR_CONVERSATION_ID": "child",
            "CURSOR_TRANSCRIPT_PATH": (
                "/tmp/agent-transcripts/parent/subagents/child.jsonl"
            ),
        }
    )


def test_cursor_child_shell_recovers_from_transcript_tree(tmp_path) -> None:
    transcript = (
        tmp_path
        / "project"
        / "agent-transcripts"
        / "parent"
        / "subagents"
        / "child.jsonl"
    )
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n", encoding="utf-8")

    assert is_subagent_execution(
        env={"CURSOR_CONVERSATION_ID": "child"},
        cursor_projects_root=tmp_path,
    )


def test_unknown_or_top_level_cursor_execution_is_not_child(tmp_path) -> None:
    assert not is_subagent_execution(env={})
    assert not is_subagent_execution(
        env={"CURSOR_CONVERSATION_ID": "top-level"},
        cursor_projects_root=tmp_path,
    )

"""Words a compound statement carries are not operands of a command.

A ``for NAME in <words>`` header lists the loop variable's VALUES; whether any
of them names a path is decided by the body that dereferences the variable. And
a segment beginning with a reserved word such as ``do`` still has to be
attributed to the command inside it, or per-command operand knowledge is lost.
"""

from __future__ import annotations

from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_payload_write_targets,
)
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    resolve_command_targets,
)

# The probe recorded on the denial: every operand is a URL path component that
# the loop concatenates onto a localhost address. Nothing is written anywhere.
URL_PATH_PROBE = (
    'for p in /app /ui /universe "/orgs/upyoke"; do '
    'curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8791$p"; done'
)


def test_a_loop_word_list_of_url_paths_names_no_filesystem_target() -> None:
    targets, unresolved = resolve_command_targets(URL_PATH_PROBE)
    assert "/app" not in targets
    assert "/ui" not in targets
    assert "/universe" not in targets
    assert "/orgs/upyoke" not in targets
    assert unresolved is False


def test_a_curl_format_string_is_not_a_worktree_path() -> None:
    """``-w`` is curl's write-out format. The reserved word opening the segment
    used to hide the command name, so it was read as ``--worktree-path``."""
    targets, _ = resolve_command_targets(URL_PATH_PROBE)
    assert "%{http_code}" not in targets


def test_a_select_word_list_is_carried_the_same_way() -> None:
    targets, _ = resolve_command_targets(
        'select choice in /etc/one /etc/two; do echo "$choice"; done'
    )
    assert "/etc/one" not in targets
    assert "/etc/two" not in targets


def test_a_path_operand_outside_a_word_list_is_still_a_target() -> None:
    targets, _ = resolve_command_targets("git -C /Users/me/lane status")
    assert "/Users/me/lane" in targets


def test_a_flag_operand_after_a_reserved_word_still_resolves() -> None:
    """Stripping the reserved word is what lets the real flag be read."""
    targets, _ = resolve_command_targets(
        "if true; then git -C /Users/me/lane log; fi"
    )
    assert "/Users/me/lane" in targets


def test_a_write_inside_a_loop_body_is_a_write_target() -> None:
    """The reserved word used to mask the command base, so a copy in a loop
    body reached the write walk as ``do`` and named no destination."""
    targets = extract_payload_write_targets(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "for f in a b; do cp /Users/me/src.txt /Users/me/out.txt; done"
                )
            },
        }
    )
    assert "/Users/me/out.txt" in targets


def test_a_redirect_inside_a_loop_body_is_a_write_target() -> None:
    targets = extract_payload_write_targets(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": "for f in a b; do echo x > /Users/me/out.txt; done"
            },
        }
    )
    assert "/Users/me/out.txt" in targets

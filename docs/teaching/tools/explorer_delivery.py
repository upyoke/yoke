"""Describe hook delivery messages and guard output in the teaching guide."""

HOOK_DESCRIPTIONS = {
    "session_dispatch": "Keeps the session registration and lifecycle state up to date.",
    "session_resume_block": "If a paused session resumes, show its pending resume notice once.",
    "session_message_delivery": "If messages are waiting, deliver them when this harness can show them to the agent.",
    "session_launch_attestation": "If this session was launched with instructions, show the sender, instructions and acknowledgement command.",
    "session_broker_wake": "If another session needs waking, supply one command to run once; do not forward the request.",
    "heartbeat": "Records that this session is still active. Usually adds no message.",
    "observe_pre": "Records the tool activity for Yoke. Usually adds no message.",
    "observe": "Records the tool result for Yoke. Usually adds no message.",
}


def add_delivery_topics(nodes):
    """Describe the prose delivered, independently of the delivery implementation."""
    topics = {
        "session_message_delivery": (
            (
                "Delivery boundaries",
                "Start and end markers identify this delivery and its message.",
            ),
            (
                "Sender",
                "Who sent the message, including the actor and session or surface.",
            ),
            (
                "Message body",
                "The message text, quoted line by line. Actual length varies with the sender’s content.",
            ),
            (
                "Reminder",
                "If already shown: how many times, and whether to act or acknowledge it.",
            ),
            (
                "Read the full message",
                "Long reminders show up to 400 body characters, with a yoke messages get command.",
            ),
            (
                "Acknowledge",
                "A yoke messages acknowledge command for the delivered message.",
            ),
            (
                "More waiting messages",
                "If messages do not fit, show the remaining count and commands to list and read them.",
            ),
        ),
        "session_resume_block": (
            (
                "Session resumed",
                "Explains that the session ended and has now reactivated.",
            ),
            (
                "Previous work claims",
                "Lists the work claims recorded when the session reactivated.",
            ),
            (
                "Reclaimed or conflicting work",
                "Shows counts of automatically reacquired claims and conflicts, when present.",
            ),
            (
                "Resume work",
                "Offers /yoke charge to select work and yoke claims work acquire to claim it explicitly.",
            ),
        ),
    }
    for node in list(nodes):
        module = node.get("hook_module", "").rsplit(".", 1)[-1]
        if module not in topics:
            continue
        node["message_estimate"] = dict(
            label="Output · variable lines and bytes",
            assumptions="Depends on message bodies and waiting messages."
            if module == "session_message_delivery"
            else "Depends on previous work claims and their outcomes.",
        )
        for index, (title, prose) in enumerate(topics[module]):
            nodes.append(
                dict(
                    id=node["id"] + ":text:" + str(index),
                    parent=node["id"],
                    title=title,
                    summary=prose,
                    form=("section", "Text section", "Delivered message content"),
                )
            )


CHECK_OUTPUT_TITLES = {
    "lint_shell_backtick_search": "Quote search text so backticks cannot execute",
    "lint_local_privacy": "This command crosses a private-data boundary",
    "lint_unmatched_path_glob": "Fix the file pattern or search option",
    "lint_db_cmd": "Use the supported database or session command",
    "lint_main_commit": "Commit implementation work in your worktree",
    "lint_tc_label": "Use descriptive test names and labels",
    "lint_long_command_polling": "Use the watcher instead of repeatedly polling",
    "lint_pipe_to_truncator": "Do not truncate a running command’s output",
    "lint_raw_pytest_full_suite": "Run the full test suite through the watcher",
    "lint_watcher_module_form": "Use the current watcher command",
    "lint_headless_watcher_timeout": "Set the required watcher timeout",
    "lint_if_status_capture": "Capture the failed command’s actual exit status",
    "lint_subagent_background": "Subagents must finish within their own turn",
    "lint_subagent_fleet_messaging": "Leave fleet message changes to the parent agent",
    "lint_session_cwd": "Use the folder authorized for this session",
    "lint_lane_main_write": "Write implementation files in your claimed worktree",
    "lint_workspace_cwd_match": "Run this write from the correct checkout",
    "path_claim_bash_guard": "This file change needs the correct path claim",
    "lint_structured_field_transform_shell": "Use the supported structured-field update",
    "lint_yoke_adapter_stderr_visibility": "Keep diagnostic errors visible",
    "lint_yoke_quoted_shell_substitution": "Prevent shell substitution inside Yoke arguments",
    "lint_no_agent_runtime_api_import_from_c": "Use the Yoke CLI instead of importing its runtime",
    "lint_no_agent_curl_against_yoke_api": "Use the Yoke CLI instead of curl",
    "lint_no_agent_session_end": "Release work claims; let the harness end the session",
    "lint_claim_ownership_mutations": "Do not bypass another session’s work claim",
    "lint_git_stash_arg_order": "Put the stash message flag before the path separator",
    "lint_destructive_git": "Protect uncommitted work before destructive Git operations",
    "path_claim_pre_edit_guard": "This edit needs the correct path claim",
    "lint_write_path": "Fix literal shell variables or unsupported secret references",
    "lint_python_runtime_import_in_tmp": "Use a supported command instead of a temporary runtime script",
    "hint_file_line_limit_approach": "This file is approaching the line limit",
    "lint_monitor_watcher_tail": "Use the watcher’s completion-aware monitor command",
    "db_error_hook": "Investigate the database error or unexpected write result",
    "turn_end_promised_work_gate": "Finish pending work or deliberately park before stopping",
}

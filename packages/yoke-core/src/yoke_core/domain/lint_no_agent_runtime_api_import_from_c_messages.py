"""Denial text for the agent-surface ``python -c`` import guard.

Kept beside the rule rather than inside it: the standing alternatives are the
bulk of the message and change on their own schedule, while the rule itself is
the matching logic. Anti-pattern teaching lives in denial messages and nowhere
else, so this is the only home for it.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.denial_identity import attach_check_id

CHECK_ID = "lint-no-agent-runtime-api-import-from-c"

STANDING_TEXT = (
    "BLOCKED: `python3 -c` that imports Yoke code is not an agent shape; it "
    "skips claim gates, telemetry and help. This rule matches only `-c` "
    "import one-liners: read-only probes whose imported names are read-shaped "
    "pass, and module invocations (`python3 -m`) are not inspected, which "
    "grants them no authority.\n\n"
    "Instead:\n"
    "  - a registered command (`yoke --help` lists them), e.g. "
    "`yoke items get PREFIX-N status`\n"
    "  - smoke-test lane source: `yoke dev import-check yoke_core.domain.<module>`\n"
    "  - run lane source: `yoke dev run -- python3 -c '<body>'`\n"
    "  - no command covers it: ask the control-plane operator for one; keep "
    "the request and the selected connection."
)


def attribution(matched: str, ordinal: int, interpreter: str) -> str:
    """Name the invocation that matched, and the statement it matched.

    A compound command offers no way to tell which invocation tripped the
    rule. One refusal naming neither was read, in good faith, as firing on a
    heredoc that was only editing a file, when it had in fact matched a
    genuine reach-in in a later segment — and that wrong cause was filed as a
    defect against the wrong behaviour.
    """
    where = f"invocation #{ordinal}" if ordinal else "an invocation"
    shape = f"`{interpreter} -c ...`" if interpreter else "`python -c ...`"
    return (
        f"Matched interpreter {where} in this command, {shape}:\n"
        f"    {matched}\n\n"
        "Only that invocation is refused; this rule did not examine other "
        "segments, such as a heredoc that edits a file.\n\n"
    )


def format_reason(
    *,
    suppression_token: str,
    suppression_seen: bool,
    matched: str = "",
    ordinal: int = 0,
    interpreter: str = "",
) -> str:
    body = STANDING_TEXT
    if matched:
        body = attribution(matched, ordinal, interpreter) + body
    if suppression_seen:
        body = (
            body + f"\n\nSuppression token `{suppression_token}` is recorded "
            "as audit evidence (outcome=suppression_attempted) but does NOT "
            "unblock."
        )
    return attach_check_id(body, check_id=CHECK_ID)


__all__ = ["CHECK_ID", "STANDING_TEXT", "attribution", "format_reason"]

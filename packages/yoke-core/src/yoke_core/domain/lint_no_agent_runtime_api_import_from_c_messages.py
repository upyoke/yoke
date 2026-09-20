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
    'BLOCKED: `python3 -c "from yoke_core..."` is not the agent-facing shape '
    "for Yoke operations.\n\n"
    "The unified `yoke` CLI and HTTP function-call surface cover every "
    'operation the dispatcher exposes — reaching for `python3 -c "..."` '
    "bypasses claim-aware gates, telemetry, and help-text affordances.\n\n"
    'This rule targets ONLY `python3 -c "..."` import one-liners. '
    "Read-only constant and inspection probes are allowed when every "
    "imported symbol and call has an explicit read-shaped name. "
    "`python3 -m <module>` module invocations are a sanctioned "
    "execution shape and are never blocked by this rule.\n\n"
    "Clean alternatives (preferred order):\n"
    "  1. Canonical agent shape — `yoke <subcommand>` covers the\n"
    "     canonical set (items get / progress-log append / structured-field\n"
    "     replace / lifecycle transition / events query / claims work\n"
    "     acquire+release / claims path register+widen / ouroboros\n"
    "     field-note append). Run `yoke --help` for the grouped\n"
    "     catalog. Examples:\n"
    "       yoke items get YOK-N status\n"
    "       yoke claims work acquire --item YOK-N --reason TEXT\n"
    "  2. Operator-debug fallback inside a Yoke checkout — for\n"
    "     function ids not yet wrapped under the `yoke` CLI:\n"
    "       python3 -m yoke_core.cli.db_router items get YOK-N status\n"
    "  3. Running this checkout's own source — `yoke dev run --` in front of\n"
    "     the interpreter is the mandated shape for lane source, and is\n"
    "     exempt however many lines its body spans:\n"
    "       yoke dev run -- python3 -c '<body>'\n"
    "  4. HTTP function-call surface — any registered function id:\n"
    "       python3 -m yoke_core.tools.api_server start\n"
    "       curl -sS -X POST http://localhost:8765/v1/functions/call \\\n"
    "           -H 'Content-Type: application/json' \\\n"
    "           --data-binary @/tmp/envelope.json\n"
    "  5. In-tree Python — if you need a script, place it under \n"
    "     runtime/api/tools/<name>.py where imports resolve natively.\n\n"
    "Doctrine: AGENTS.md `## Code Conventions` → Operational primitives "
    "— the unified `yoke` CLI is the canonical agent interface; "
    "ad-hoc `yoke_core.*` / `runtime.*` reach-in is infrastructure / debug "
    "surface, not an agent shape."
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
        "That invocation alone is refused. No other segment of this command "
        "body was examined for this rule — in particular a heredoc that only "
        "edits a file does not trip it, so read the statement above before "
        "concluding what did.\n\n"
    )


def format_reason(
    *,
    suppression_token: str,
    suppression_seen: bool,
    mode: str,
    matched: str = "",
    ordinal: int = 0,
    interpreter: str = "",
) -> str:
    body = STANDING_TEXT
    if matched:
        body = attribution(matched, ordinal, interpreter) + body
    if mode == "warn":
        body = body + "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body = (
            body + f"\n\nSuppression token `{suppression_token}` is recorded "
            "as audit evidence (outcome=suppression_attempted) but does NOT "
            "unblock."
        )
    return attach_check_id(body, check_id=CHECK_ID)


__all__ = ["CHECK_ID", "STANDING_TEXT", "attribution", "format_reason"]

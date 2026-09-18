"""Denial copy for the yoke double-quoted shell-substitution lint."""

from __future__ import annotations

from yoke_core.domain.denial_field_note_footer import append_field_note_footer

CHECK_ID = "lint-yoke-quoted-shell-substitution"
HOOK_NAME = "lint-yoke-quoted-shell-substitution"
SUPPRESSION_TOKEN = "# lint:no-yoke-quoted-substitution-check"

SAFE_FORM = (
    "Pass free text on --stdin or --content-file from a quoted heredoc "
    "(<<'EOF'), which the shell does not expand:\n"
    "  yoke dash TITLE --stdin --execution-instructions-considered <<'EOF'\n"
    "  instruction that names `yoke items get` and $(whoami) literally\n"
    "  EOF\n"
    "  printf '%s' \"$instruction\" | yoke dash TITLE --stdin "
    "--execution-instructions-considered\n"
    "For a computed value, capture first, then pass the variable:\n"
    "  sha=$(git rev-parse HEAD)\n"
    "  yoke ... --source-ref \"$sha\""
)


def format_reason(span: str, suppression_seen: bool, mode: str) -> str:
    preview = span if len(span) <= 160 else span[:157] + "..."
    body = (
        "BLOCKED: a `yoke` invocation carries backticks or $( inside a "
        "double-quoted argument.\n\n"
        f"Quoted argument: {preview!r}\n\n"
        "The shell expands those forms before Yoke runs, so the command "
        "Yoke receives is already substituted. "
        f"{SAFE_FORM}\n"
    )
    if mode == "warn":
        body += "\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return append_field_note_footer(body, rule_id=CHECK_ID)

"""Denial copy for the yoke double-quoted shell-substitution lint."""

from __future__ import annotations

from yoke_contracts.hook_runner.denial_identity import attach_check_id

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

QUOTE_THE_DELIMITER = (
    "An unquoted delimiter leaves the body expanded, so quote it and the same "
    "text arrives literally:\n"
    "  yoke ... --stdin <<'EOF'\n"
    "  body that names `yoke items get` and $(whoami) literally\n"
    "  EOF"
)

_ARGUMENT_HEADLINE = (
    "BLOCKED: a `yoke` invocation carries backticks or $( inside a "
    "double-quoted argument."
)
_HEREDOC_HEADLINE = (
    "BLOCKED: a `yoke` invocation feeds a heredoc whose delimiter is "
    "unquoted, and its body carries backticks or $(."
)
_LABELS = {"argument": "Quoted argument", "heredoc": "Heredoc body"}
_HEADLINES = {"argument": _ARGUMENT_HEADLINE, "heredoc": _HEREDOC_HEADLINE}
_RECOVERIES = {"argument": SAFE_FORM, "heredoc": QUOTE_THE_DELIMITER}


def format_reason(
    kind: str, text: str, suppression_seen: bool, mode: str
) -> str:
    preview = text if len(text) <= 160 else text[:157] + "..."
    body = (
        f"{_HEADLINES[kind]}\n\n"
        f"{_LABELS[kind]}: {preview!r}\n\n"
        "The shell expands those forms before Yoke runs, so the command "
        "Yoke receives is already substituted. "
        f"{_RECOVERIES[kind]}\n"
    )
    if mode == "warn":
        body += "\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return attach_check_id(body, check_id=CHECK_ID)

"""The stdout-truncation half of the Yoke adapter output guard.

A registered ``yoke`` adapter prints its whole answer on purpose: a read
serves the fields the caller asked for, and a refusal prints its named
reason plus the recovery step. Piping that into ``head`` or ``tail``
keeps a byte window and throws the rest away — including the refusal a
non-zero exit status was pointing at — so the caller reads silence or a
half-record and concludes the wrong thing. Narrowing belongs in the
request: name the field, add ``--json`` and select from the envelope, or
call the narrow read instead of slicing a wide one.

This module owns two things the sibling stderr rule also needs: the
``yoke``-stage parsing shared by both rules, and the truncation rule
itself. Both are consumed by the one registered guard in
:mod:`yoke_core.domain.lint_yoke_adapter_stderr_visibility`, which stays
the single check id, hook registration, and audit emitter.

``--help`` invocations are out of scope. Their output is reference prose
a reader legitimately pages through, and the guard is deliberately narrow:
it allows every shape it cannot classify confidently.
"""

from __future__ import annotations

import os
import shlex
from typing import Optional

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.path_claim_bash_splitter import iter_pipeline_groups

TRUNCATORS = frozenset({"head", "tail"})


def stage_tokens(stage: str) -> list[str]:
    """Split one pipeline stage into tokens, tolerating unbalanced quotes."""
    try:
        tokens = shlex.split(stage, posix=True)
    except ValueError:
        return []
    if tokens:
        tokens[0] = tokens[0].lstrip("({")
    return [token for token in tokens if token]


def yoke_args(stage: str) -> list[str]:
    """Return arguments for a direct ``yoke`` stage, else an empty list.

    Leading ``VAR=value`` assignments and an ``env`` prefix are skipped so
    ``YOKE_X=1 env YOKE_Y=2 yoke ...`` classifies like a bare invocation,
    and a leading ``--env NAME`` connection selector is dropped so the
    caller's subcommand path starts at index zero.
    """
    tokens = stage_tokens(stage)
    if not tokens:
        return []
    index = 0
    while index < len(tokens) and "=" in tokens[index]:
        index += 1
    if index < len(tokens) and os.path.basename(tokens[index]) == "env":
        index += 1
        while index < len(tokens) and "=" in tokens[index]:
            index += 1
    if index >= len(tokens) or os.path.basename(tokens[index]) != "yoke":
        return []
    args = tokens[index + 1 :]
    while args:
        if args[0] == "--env" and len(args) >= 2:
            args = args[2:]
            continue
        if args[0].startswith("--env="):
            args = args[1:]
            continue
        break
    return args


def _adapter_label(args: list[str]) -> str:
    """Name the invocation by its subcommand path, without its arguments."""
    path = [token for token in args if not token.startswith("-")][:2]
    return "yoke " + " ".join(path) if path else "yoke"


def _is_truncator(stage: str) -> bool:
    tokens = stage_tokens(stage)
    if not tokens:
        return False
    return os.path.basename(tokens[0]) in TRUNCATORS


def find_truncation_violation(command: str) -> Optional[tuple[str, str]]:
    """Return ``(adapter label, truncator)`` for a truncated ``yoke`` stage."""
    for stages in iter_pipeline_groups(command):
        for index, stage in enumerate(stages):
            args = yoke_args(stage)
            if not args or any(token in {"--help", "-h"} for token in args):
                continue
            for later in stages[index + 1 :]:
                if _is_truncator(later):
                    return _adapter_label(args), os.path.basename(
                        stage_tokens(later)[0]
                    )
    return None


#: Per-class recovery, keyed on the first word of the caught subcommand.
#: A generic "narrow the request" did not redirect the habit across nine
#: occurrences in one session, because the caller still had to work out
#: what the narrower shape was for the command it had just written. Each
#: entry names a shape reachable for the command that triggered the block.
_CLASS_RECOVERY: dict[str, tuple[str, ...]] = {
    "watch": (
        "The wrapper streams its own progress and prints a raw capture "
        "path; read that file once the run exits.",
    ),
    "db": (
        "The columns, the filter, and the row count are part of the "
        "query: SELECT the columns you want and add a LIMIT.",
    ),
    "messages": (
        "yoke messages get MESSAGE-ID body        # the field you came for",
        "yoke messages list --state pending       # one row per message",
    ),
    "items": (
        "yoke items get PREFIX-N status           # name the fields you want",
        'yoke items get PREFIX-N spec --section "## Heading"',
    ),
    "qa": (
        "The routine read is the default; --full serves what its summary "
        "named as held back.",
    ),
}


def _recovery_lines(label: str) -> tuple[str, ...]:
    """Name the narrower shape for the command class that was caught."""
    family = label.split()[1] if len(label.split()) > 1 else ""
    specific = _CLASS_RECOVERY.get(family, ())
    # The fallback names only shapes every registered adapter accepts: a
    # bare invocation, and --json. A `--full` suggested at a command that
    # has no such flag would send the caller into a second refusal.
    return specific or (
        f"{label} <arguments>          # run it bare; reads are already scoped",
        f"{label} <arguments> --json   # the envelope, when you need its shape",
    )


def truncation_reason(
    label: str,
    truncator: str,
    suppression_seen: bool,
    mode: str,
    *,
    check_id: str,
    suppression_token: str,
) -> str:
    """Render the refusal, naming the narrower read to run instead."""
    recovery = "\n".join(f"  {line}" for line in _recovery_lines(label))
    body = (
        f"BLOCKED: Yoke adapter output truncated (`{label}` piped into "
        f"`{truncator}`).\n\n"
        "A registered adapter prints its answer whole, and a refusal prints "
        "its named reason and recovery step. Keeping a byte window discards "
        "the rest and hides the exit status the window did not reach.\n\n"
        f"Ask the narrow question instead — for `{label}`:\n"
        f"{recovery}\n\n"
        "`yoke <command> --help` ends with the recipe, and `yoke --help` "
        "carries the catalog. To keep a long run's whole output, capture it "
        "to a file and read the file:\n"
        "  _tmp=$(mktemp /tmp/yoke-cmd.XXXXXX); <command> >\"$_tmp\" 2>&1; "
        '_rc=$?; tail -80 "$_tmp"'
    )
    if mode == "warn":
        body += "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\n\nSuppression token `{suppression_token}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return attach_check_id(body, check_id=check_id)


__all__ = [
    "TRUNCATORS",
    "find_truncation_violation",
    "stage_tokens",
    "truncation_reason",
    "yoke_args",
]

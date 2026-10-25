"""Remote-operand indexes the session-cwd extractor skips.

``yoke qa mission host-command ... -- ARGV...`` ships everything after
the ``--`` separator over an awaiting mission execution's retained Test
Machine lease and runs it on that **remote** host. Paths in that argv
name the Test Machine's filesystem, never this machine's, so the
session-cwd write-authority lint must not read them as local write
targets: doing so refused ``-- /bin/ls /Users/testy`` while letting
path-free ``-- /bin/pwd`` through, narrowing the mission instrument to
commands that happen to mention no path at all. The ``--from`` value of
``yoke qa mission host-copy`` names a Test Machine file the same way; its
``--to`` value is a local write target and stays one.

``aws logs`` / ``yoke aws exec -- logs`` ``--log-group-name`` operands
name a CloudWatch group on another machine. ``aws ssm`` /
``yoke aws exec -- ssm`` ``--name``, ``--names`` and ``--path`` operands
name a parameter, not a file. ``file://`` / ``fileb://`` values load a
local file and stay path targets.

The shell target extractor
(:mod:`lint_session_cwd_target_extract_shell`) consumes
:func:`remote_argv_indexes`, :func:`aws_log_group_indexes` and
:func:`aws_ssm_parameter_indexes` to skip those tokens, and the denial
renderer
(:mod:`lint_session_cwd_control_plane`) consumes
:func:`host_command_exemption_note` so an invocation that is still
refused for some other reason says why the exemption did not cover the
target it named.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_core.domain.lint_shell_target_tokens import unwrap_cli_file_param


HOST_COMMAND_SUBCOMMAND = ("qa", "mission", "host-command")
HOST_COPY_SUBCOMMAND = ("qa", "mission", "host-copy")
TEST_MACHINE_EXEC_SUBCOMMAND = ("test-machine", "exec")

# Global ``yoke`` flags whose value must not be mistaken for a subcommand.
YOKE_VALUE_FLAGS = frozenset({"--env", "--config", "--session-id"})

EXEMPTION_NOTE = (
    "\nhost-command remote-argv exemption: this call is `yoke qa mission "
    "host-command`, whose argv after `--` runs on the Test Machine over "
    "the mission's retained lease. Those paths were NOT classified as "
    "local write targets. The target named above came from the part of "
    "the call that does run locally — a redirect, a flag value, or the "
    "call's own working directory. Correct that local target, or run the "
    "command from a path this session's claim covers.\n"
)


def yoke_subcommand_positionals(
    tokens: Sequence[str],
    *,
    limit: int,
) -> List[str]:
    """Return up to ``limit`` subcommand positionals of a ``yoke`` segment.

    Walks past the ``yoke`` head, consuming the value of every global
    flag in :data:`YOKE_VALUE_FLAGS` so ``yoke --env prod qa mission ...``
    reports the same subcommand as the bare form. Stops at a ``--``
    separator: everything beyond it is operand text, not subcommand
    naming.
    """
    positionals: List[str] = []
    seen_command = False
    index = 0
    while index < len(tokens) and len(positionals) < limit:
        token = tokens[index]
        if token == "--":
            break
        if token in YOKE_VALUE_FLAGS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if not seen_command:
            seen_command = True
            index += 1
            continue
        positionals.append(token)
        index += 1
    return positionals


def _invokes(
    command_base: str, tokens: Sequence[str], subcommand: Tuple[str, ...]
) -> bool:
    if command_base != "yoke":
        return False
    positionals = yoke_subcommand_positionals(tokens, limit=len(subcommand))
    return tuple(positionals) == subcommand


def is_host_command_segment(command_base: str, tokens: Sequence[str]) -> bool:
    """True when ``tokens`` invoke ``yoke qa mission host-command``."""
    return _invokes(command_base, tokens, HOST_COMMAND_SUBCOMMAND)


def is_test_machine_exec_segment(command_base: str, tokens: Sequence[str]) -> bool:
    """True when ``tokens`` invoke ``yoke test-machine exec``."""
    if command_base != "yoke":
        return False
    positionals = yoke_subcommand_positionals(
        tokens,
        limit=len(TEST_MACHINE_EXEC_SUBCOMMAND),
    )
    return tuple(positionals) == TEST_MACHINE_EXEC_SUBCOMMAND


def test_machine_exec_argv_indexes(
    command_base: str,
    tokens: Sequence[str],
) -> set[int]:
    """Every argument of ``yoke test-machine exec`` runs on the remote host.

    The words name that machine's filesystem. A shell redirect is not one
    of them — the extractor resolves redirects before consulting this set.
    """
    if not is_test_machine_exec_segment(command_base, tokens):
        return set()
    for index, token in enumerate(tokens):
        if token == "exec":
            return set(range(index + 1, len(tokens)))
    return set()


def remote_argv_indexes(command_base: str, tokens: Sequence[str]) -> set[int]:
    """Return the token indexes that run on the remote Test Machine.

    Empty for every segment that is not a host-command or host-copy
    invocation, and for a host-command invocation written without the
    ``--`` separator (which the CLI itself rejects). Otherwise every index
    after the separator, because the whole argv is shipped over the lease.
    For host-copy, only the ``--from`` value.

    Shell redirect syntax trailing that argv is not part of it — the
    shell performs a redirect on this machine — so the extractor
    resolves redirects before consulting this index set.
    """
    if _invokes(command_base, tokens, HOST_COPY_SUBCOMMAND):
        return {
            index + 1 if token == "--from" else index
            for index, token in enumerate(tokens)
            if token.startswith("--from=")
            or (token == "--from" and index + 1 < len(tokens))
        }
    if not is_host_command_segment(command_base, tokens):
        return set()
    try:
        separator = list(tokens).index("--")
    except ValueError:
        return set()
    return set(range(separator + 1, len(tokens)))


def local_argv_text(segment: str) -> str:
    """Return one invocation's text without the argv a host-command ships.

    The path-claim guard fails closed on an opaque ``sh -c`` body, but one
    that ``host-command`` runs on the Test Machine is a remote argv word.
    Redirects and substitutions still run here, so callers keep reading
    them from the full segment.
    """
    parsed = parse_shell(segment)
    if parsed.unparsed or len(parsed.segments) != 1:
        return segment
    words = parsed.segments[0]
    remote = remote_argv_indexes(words.program, words.argv)
    if not remote:
        return segment
    prefix = words.tokens[: len(words.tokens) - len(words.argv)]
    local = [tok for i, tok in enumerate(words.argv) if i not in remote]
    return " ".join([*prefix, *local])


_AWS_VALUE_FLAGS = frozenset(
    {
        "--region",
        "--profile",
        "--output",
        "--endpoint-url",
    }
)
_LOG_GROUP_FLAGS = frozenset({"--log-group-name", "--log-group"})
_LOG_GROUP_EQUALS = ("--log-group-name=", "--log-group=")
_SSM_SINGLE_VALUE_FLAGS = frozenset({"--name", "--path"})
_SSM_EQUALS_PREFIXES = ("--name=", "--names=", "--path=")


def _aws_cli_argv(
    command_base: str,
    tokens: Sequence[str],
) -> Optional[Tuple[List[str], int]]:
    """Return AWS CLI argv and its start index for ``aws`` / ``yoke aws exec``."""
    inner = list(tokens)
    if command_base == "aws":
        return inner, 0
    if command_base != "yoke":
        return None
    try:
        sep = inner.index("--")
        aws_at = inner.index("aws", 1, sep)
    except ValueError:
        return None
    if inner[aws_at : aws_at + 2] != ["aws", "exec"]:
        return None
    return inner[sep + 1 :], sep + 1


def _aws_service(inner: Sequence[str]) -> str:
    """Return the AWS service token (``logs``, ``s3``, …), skipping globals."""
    i = 1 if inner and inner[0].rsplit("/", 1)[-1] == "aws" else 0
    while i < len(inner):
        tok = inner[i]
        if tok in _AWS_VALUE_FLAGS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok
    return ""


def aws_log_group_indexes(command_base: str, tokens: Sequence[str]) -> set[int]:
    """Indexes of CloudWatch log-group operands on a recognized ``logs`` argv.

    ``file://`` / ``fileb://`` values load a local file and are not skipped.
    Other AWS services keep full path extraction, including a misplaced
    ``--log-group-name``.
    """
    argv = _aws_cli_argv(command_base, tokens)
    if argv is None or _aws_service(argv[0]) != "logs":
        return set()
    inner, offset = argv
    indexes: set[int] = set()
    for i, tok in enumerate(inner):
        if tok in _LOG_GROUP_FLAGS and i + 1 < len(inner):
            if unwrap_cli_file_param(inner[i + 1]) == inner[i + 1]:
                indexes.add(offset + i + 1)
            continue
        eq = next((p for p in _LOG_GROUP_EQUALS if tok.startswith(p)), "")
        if eq and unwrap_cli_file_param(tok[len(eq) :]) == tok[len(eq) :]:
            indexes.add(offset + i)
        if (
            tok == "logs"
            and i + 2 < len(inner)
            and inner[i + 1] == "tail"
            and not inner[i + 2].startswith("-")
            and unwrap_cli_file_param(inner[i + 2]) == inner[i + 2]
        ):
            indexes.add(offset + i + 2)
    return indexes


def _remote_cli_value(value: str) -> bool:
    """True when an AWS value is not a local ``file://`` / ``fileb://`` load."""
    return bool(value) and unwrap_cli_file_param(value) == value


def aws_ssm_parameter_indexes(command_base: str, tokens: Sequence[str]) -> set[int]:
    """Indexes of SSM parameter name and path operands on an ``ssm`` argv.

    ``--name`` and ``--path`` take one value. ``--names`` takes each
    following value until the next flag. ``file://`` / ``fileb://`` values
    load a local file and are not skipped. Other services keep path
    extraction, including a misplaced parameter flag.
    """
    argv = _aws_cli_argv(command_base, tokens)
    if argv is None or _aws_service(argv[0]) != "ssm":
        return set()
    inner, offset = argv
    indexes: set[int] = set()
    index = 0
    limit = len(inner)
    while index < limit:
        token = inner[index]
        if token == "--names":
            index += 1
            while index < limit and not inner[index].startswith("-"):
                if _remote_cli_value(inner[index]):
                    indexes.add(offset + index)
                index += 1
            continue
        if token in _SSM_SINGLE_VALUE_FLAGS and index + 1 < limit:
            if _remote_cli_value(inner[index + 1]):
                indexes.add(offset + index + 1)
            index += 2
            continue
        prefix = next(
            (item for item in _SSM_EQUALS_PREFIXES if token.startswith(item)),
            "",
        )
        if prefix and _remote_cli_value(token[len(prefix) :]):
            indexes.add(offset + index)
        index += 1
    return indexes


def is_host_command(command: str | ShellParse) -> bool:
    """True when any invocation in ``command`` is a host-command call."""
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    return any(
        is_host_command_segment(segment.program, segment.argv)
        for segment in parsed.segments
    )


def host_command_exemption_note(command: str | ShellParse) -> str:
    """Return the denial clause for a refused host-command call, else ``""``."""
    if not command or not is_host_command(command):
        return ""
    return EXEMPTION_NOTE


__all__ = [
    "EXEMPTION_NOTE",
    "HOST_COMMAND_SUBCOMMAND",
    "HOST_COPY_SUBCOMMAND",
    "YOKE_VALUE_FLAGS",
    "aws_log_group_indexes",
    "aws_ssm_parameter_indexes",
    "host_command_exemption_note",
    "is_host_command",
    "is_host_command_segment",
    "is_test_machine_exec_segment",
    "local_argv_text",
    "remote_argv_indexes",
    "test_machine_exec_argv_indexes",
    "yoke_subcommand_positionals",
]

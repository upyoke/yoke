"""Resolve PowerShell mutation targets for shared path-claim enforcement.

The PowerShell twin of :mod:`path_claim_bash_parser`: it reads the shared
PowerShell parse and yields the same :class:`Mutation` tuples, so
``path_claim_bash_guard`` judges both shells by one claim rule.

- File cmdlets and their aliases (``Set-Content``, ``Out-File``,
  ``Remove-Item``/``rm``/``del``, ``Copy-Item``/``cp``, ``Move-Item``/``mv``,
  ``New-Item``/``mkdir``...) yield their ``-Path``/``-LiteralPath``/
  ``-FilePath``/``-Destination`` or positional targets.
- ``>``/``>>`` (any stream, ``2>``, ``*>``) yield their target unless it is
  ``$null``. Targets under ``$env:TEMP``/``$env:TMP`` are scratch.
- ``git rm|restore|checkout`` reuse the Bash parser's Git rule.
- Opaque execution (``Invoke-Expression``/``iex``, ``powershell -Command``,
  ``pwsh -c``, ``cmd /c``, ``bash -c``, ``sh -c``) and unparseable text yield
  an ``ambiguous`` sentinel and fail closed.
- The suppression token yields an auditable ``suppressed`` sentinel.

A ``Set-Location`` after the first command moves later relative targets; one
the parser cannot read marks them ``cwd_unresolved``.
"""

from __future__ import annotations

import os
import re
from typing import List, Sequence

from yoke_contracts.hook_runner.powershell_parse import parse_powershell
from yoke_contracts.hook_runner.shell_parse import ShellParse, advance_cwd, cd_destination
from yoke_core.domain.path_claim_bash_parser import (
    SUPPRESSION_TOKEN,
    Mutation,
    _extract_git_paths,
)
from yoke_core.domain.path_claim_bash_segment_cwd import rebase_targets

_REDIRECT = re.compile(r"^(?:[1-6*])?(>>?)(.*)$")
_PATH_PARAMS = frozenset({"-path", "-literalpath", "-lp", "-pspath", "-filepath"})
_DESTINATION_PARAMS = frozenset({"-destination"})
_NAME_PARAMS = frozenset({"-name", "-newname"})
_SWITCHES = frozenset(
    {
        "-append", "-confirm", "-container", "-force", "-noclobber", "-nonewline",
        "-passthru", "-recurse", "-whatif", "-asbytestream", "-verbose",
    }
)
_ALIASES = {
    "sc": "set-content", "ac": "add-content", "clc": "clear-content",
    "ni": "new-item", "mkdir": "new-item", "md": "new-item",
    "rm": "remove-item", "del": "remove-item", "erase": "remove-item",
    "rd": "remove-item", "rmdir": "remove-item", "ri": "remove-item",
    "cp": "copy-item", "copy": "copy-item", "cpi": "copy-item",
    "mv": "move-item", "move": "move-item", "mi": "move-item",
    "ren": "rename-item", "rni": "rename-item", "tee": "tee-object",
}
# Cmdlet -> (all positionals are targets, positional index of the target).
_FIRST_PATH = frozenset(
    {"set-content", "add-content", "out-file", "tee-object", "new-item", "rename-item"}
)
_ALL_PATHS = frozenset({"remove-item", "clear-content"})
_TO_DESTINATION = frozenset({"copy-item", "move-item"})
_OPAQUE = frozenset({"invoke-expression", "iex"})
_INLINE_SHELLS = {
    "powershell": ("-command", "-c", "-encodedcommand", "-ec"),
    "pwsh": ("-command", "-c", "-encodedcommand", "-ec"),
    "cmd": ("/c", "/k"),
    "bash": ("-c",),
    "sh": ("-c",),
}


def _is_scratch(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    return lowered.startswith(("$env:temp", "$env:tmp")) or lowered in ("$null", "nul")


def _split_redirects(args: List[str]) -> tuple[List[str], List[Mutation]]:
    kept: List[str] = []
    out: List[Mutation] = []
    i = 0
    while i < len(args):
        match = _REDIRECT.match(args[i])
        if match is None:
            kept.append(args[i])
            i += 1
            continue
        target = match.group(2)
        if not target and i + 1 < len(args):
            target = args[i + 1]
            i += 1
        i += 1
        if target and not target.startswith("&") and not _is_scratch(target):
            out.append(Mutation(verb="redirect", target_path=target))
    return kept, out


def _join_arrays(args: List[str]) -> List[str]:
    """Rejoin a comma list split by spaces: ``a, b`` is one array argument."""
    out: List[str] = []
    for token in args:
        if out and (out[-1].endswith(",") or token.startswith(",")):
            out[-1] += token
        else:
            out.append(token)
    return out


def _parameters(args: List[str]) -> tuple[dict[str, List[str]], List[str]]:
    named: dict[str, List[str]] = {}
    positional: List[str] = []
    args = _join_arrays(args)
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("-") and len(token) > 1:
            name, _, glued = token.partition(":")
            name = name.lower()
            if glued:
                named.setdefault(name, []).append(glued)
            elif name not in _SWITCHES and i + 1 < len(args):
                named.setdefault(name, []).extend(p for p in args[i + 1].split(",") if p)
                i += 1
            i += 1
            continue
        positional.extend(part for part in token.split(",") if part)
        i += 1
    return named, positional


def _cmdlet_targets(cmdlet: str, args: List[str]) -> List[str]:
    named, positional = _parameters(args)
    paths = [p for key in _PATH_PARAMS for p in named.get(key, [])]
    if cmdlet in _TO_DESTINATION:
        destination = [p for key in _DESTINATION_PARAMS for p in named.get(key, [])]
        if not destination and len(positional) + len(paths) >= 2:
            destination = positional[-1:]
        sources = paths or positional[:1]
        return destination + (sources if cmdlet == "move-item" else [])
    if cmdlet in _ALL_PATHS:
        return paths + positional
    targets = paths or positional[:1]
    names = [n for key in _NAME_PARAMS for n in named.get(key, [])]
    if cmdlet == "new-item" and names:
        base = targets[0] if targets else ""
        return [f"{base.rstrip('/').rstrip(chr(92))}/{n}" if base else n for n in names]
    return targets


def _is_opaque(program: str, args: List[str]) -> bool:
    if program in _OPAQUE:
        return True
    flags = _INLINE_SHELLS.get(program)
    return bool(flags) and any(arg.lower() in flags for arg in args)


def _classify(program: str, argv: tuple[str, ...], cwd: str, text: str) -> List[Mutation]:
    args, out = _split_redirects(list(argv[1:]))
    if _is_opaque(program, args):
        return [Mutation(verb="ambiguous", target_path=text[:80])]
    if program == "git":
        out.extend(_extract_git_paths(args, cwd))
        return out
    cmdlet = _ALIASES.get(program, program)
    if cmdlet in _FIRST_PATH | _ALL_PATHS | _TO_DESTINATION:
        out.extend(
            Mutation(verb=cmdlet, target_path=target)
            for target in _cmdlet_targets(cmdlet, args)
            if target and not _is_scratch(target)
        )
    return out


def powershell_write_operands(
    parsed: ShellParse, segment_cwds: Sequence[str] = ()
) -> tuple[List[str], bool]:
    """Write targets of a PowerShell parse for the cwd guards, plus opacity.

    ``segment_cwds`` moves each segment's relative targets, as the Bash
    operand reader does; an opaque or unparseable segment reports
    ``unresolved`` instead of a target.
    """
    out: List[str] = []
    unresolved = bool(parsed.unparsed)
    for index, segment in enumerate(parsed.segments):
        if not segment.argv:
            continue
        for mut in _classify(segment.program, segment.argv, "", segment.text):
            if mut.verb == "ambiguous":
                unresolved = True
                continue
            folder = segment_cwds[index] if index < len(segment_cwds) else ""
            target = mut.target_path
            if folder and not os.path.isabs(target) and not target.startswith(("~", "$")):
                target = os.path.normpath(os.path.join(folder, target))
            out.append(target)
    return out, unresolved


def extract_powershell_mutations(command: str, cwd: str = "", home: str = "") -> List[Mutation]:
    """Extract ``(verb, target_path)`` tuples from a PowerShell command.

    ``cwd`` is the execution directory after leading ``Set-Location``
    statements, as for :func:`path_claim_bash_parser.extract_mutations`.
    """
    if not command or not isinstance(command, str):
        return []
    if SUPPRESSION_TOKEN in command:
        return [Mutation(verb="suppressed", target_path=SUPPRESSION_TOKEN)]
    parsed = parse_powershell(command)
    out: List[Mutation] = [
        Mutation(verb="ambiguous", target_path=text[:80]) for text in parsed.unparsed
    ]
    folder = cwd
    leading = True
    unresolved = False
    for segment in parsed.segments:
        destination = cd_destination(segment.argv)
        if destination is not None:
            if not leading and not unresolved:
                moved = advance_cwd(folder, destination, home=home)
                unresolved = not moved
                folder = moved or folder
            elif leading:
                unresolved = unresolved or not advance_cwd("/", destination, home="/")
            continue
        if segment.argv:
            leading = False
        muts = _classify(segment.program, segment.argv, folder, segment.text)
        out.extend(rebase_targets(muts, folder, cwd, unresolved))
    return out


__all__ = ["extract_powershell_mutations", "powershell_write_operands"]

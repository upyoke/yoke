"""Working folder of each Bash pipeline stage for path-claim targets.

The guard's execution cwd already follows the command's leading ``cd``
statements (:func:`command_workdir.command_execution_cwd`). A later ``cd``
moves only the statements after it, so their relative targets are joined
to the folder that ``cd`` reached. A ``cd`` inside a multi-stage pipeline
runs in a subshell and moves nothing.

A ``cd`` whose destination cannot be read (``cd $DIR``, ``cd -``) keeps
later targets on the last readable folder and marks them
``cwd_unresolved``: the guard decides as before, and the recovery text
asks for an absolute path or ``git -C`` instead of a guessed relative one.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import replace
from typing import Iterator, List, Tuple

from yoke_contracts.hook_runner.shell_parse import (
    advance_cwd,
    cd_destination,
    strip_env_prefix,
)
from yoke_contracts.hook_runner.shell_statements import iter_pipeline_groups

# Parser sentinels whose target is a command excerpt, not a path.
_NON_PATH_VERBS = frozenset({"ambiguous", "suppressed"})


def _cd_operand(stage: str) -> str | None:
    try:
        tokens = shlex.split(stage, posix=True)
    except ValueError:
        return None
    return cd_destination(strip_env_prefix(tokens))


def _readable(destination: str) -> bool:
    # The caller already resolved a leading ``cd``; only its readability
    # matters here, so any absolute base and home stand in for the real ones.
    return bool(advance_cwd("/", destination, home="/"))


def stages_with_cwd(
    command: str, cwd: str, *, home: str = ""
) -> Iterator[Tuple[str, str, bool]]:
    """Yield ``(stage, folder, cwd_unresolved)`` for each pipeline stage.

    ``cwd`` is the execution cwd after the leading ``cd`` statements.
    ``home`` expands ``~`` in a later ``cd``; ``""`` leaves it unreadable.
    """
    leading = True
    unresolved = False
    for stages in iter_pipeline_groups(command, shell_comments=True):
        destination = _cd_operand(stages[0]) if len(stages) == 1 else None
        if destination is None:
            leading = False
        elif leading:
            unresolved = unresolved or not _readable(destination)
        elif not unresolved:
            moved = advance_cwd(cwd, destination, home=home)
            unresolved = not moved
            cwd = moved or cwd
        for stage in stages:
            yield stage, cwd, unresolved


def rebase_targets(mutations: List, folder: str, base_cwd: str, unresolved: bool) -> List:
    """Join relative targets to ``folder`` when a later ``cd`` moved it.

    Targets stay as written when ``folder`` is the execution cwd; the
    target resolver joins those itself. ``~`` and ``$VAR`` targets stay
    as written for the client-home and temp-file filters downstream.
    """
    out = []
    for mut in mutations:
        target = mut.target_path
        if mut.verb in _NON_PATH_VERBS:
            out.append(mut)
            continue
        if folder != base_cwd and folder and not os.path.isabs(target):
            if not target.startswith(("~", "$")):
                target = os.path.join(folder, target)
        out.append(replace(mut, target_path=target, cwd_unresolved=unresolved))
    return out


__all__ = ["rebase_targets", "stages_with_cwd"]

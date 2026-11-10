"""Choose the command a fleet preflight runs: the local kernel or a declared executor.

A fleet preflight copies every live database of a fleet to the machine that
runs the kernel. An environment may declare ``release.preflight_executor``, a
command line that runs in place of the local kernel so the copy happens on a
host beside the database. When the setting is unset (or empty) the kernel runs
on this machine; that is the normal mode for local and self-hosted projects.

Executor contract:

- The executor receives the kernel's arguments after its own command words:
  ``--project``, ``--model``, the environment and any database names,
  ``--record-receipt``, ``--receipt-env`` and ``--run-id``. Caller-local
  paths cannot reach another host, so ``--checkout`` and ``--engine-wheel``
  refuse; ``--instant-census-output`` names a directory on the executor host.
- ``--product-sha`` identifies the source commit to rehearse. The executor
  runs that commit's kernel and fleet commands on its own host; without it,
  the executor rehearses its own installed engine, as the local kernel does.
- The caller keeps the watcher, its captures and the exit code. A release
  rehearsal does not inspect this machine's engine or make a local checkout
  for an executor run; it still re-reads the environment's receipt and
  refuses the dispatch unless the receipt covers the release commit's
  history entries and schema shape.

The setting is read from the environment the preflight's positional names,
through the same coverage read the kernel uses for ``release.admin_connection``.
A read that fails refuses rather than guessing, because guessing "unset" would
copy a declared-remote fleet onto this machine.
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from typing import Sequence

from yoke_contracts.refusal_recovery import compose_refusal

PREFLIGHT_MODULE = "yoke_core.tools.preflight_fleet_migrations"


@dataclass(frozen=True)
class PreflightCommand:
    """Where a preflight runs: the local kernel, a declared executor, or a refusal."""

    executor: str = ""
    words: tuple[str, ...] = ()
    project: str = ""
    environment: str = ""
    refusal: str = ""

    def argv(self, args: Sequence[str]) -> list[str]:
        """The argv the watcher runs for these preflight arguments."""
        if self.refusal:
            return _refusal_argv(self.refusal)
        if self.executor:
            return [*self.words, *args]
        return [sys.executable, "-m", PREFLIGHT_MODULE, *args]


def _target(args: Sequence[str]) -> tuple[str, str, tuple[str, ...]]:
    """The project, environment and caller-local path flags the arguments name."""
    from yoke_core.tools.preflight_arguments import parse

    try:
        parsed = parse(list(args))
    except (SystemExit, ValueError):
        return "", "", ()
    operands = list(parsed.operands or [])
    local_paths = tuple(
        flag
        for flag, value in (
            ("--checkout", parsed.checkout),
            ("--engine-wheel", parsed.engine_wheel),
        )
        if value
    )
    environment = operands[0].strip() if operands else ""
    return parsed.project.strip(), environment, local_paths


def _refusal_argv(message: str) -> list[str]:
    """A child that prints *message* and exits 2, so the watcher records it."""
    return [
        sys.executable,
        "-c",
        "import sys; print(sys.argv[1], file=sys.stderr); raise SystemExit(2)",
        message,
    ]


def _set_recovery(project: str, environment: str) -> str:
    return (
        "yoke projects environment-settings merge --project "
        f"{project} --environment {environment} "
        "--set release.preflight_executor=<command>"
    )


def _executor_refusal(
    reason: str, project: str, environment: str, *, recovery: str
) -> PreflightCommand:
    message = compose_refusal(reason, recovery=recovery)
    return PreflightCommand(
        project=project,
        environment=environment,
        refusal=message,
    )


def resolve(args: Sequence[str]) -> PreflightCommand:
    """The command that runs this preflight, per the environment's declaration."""
    project, environment, local_paths = _target(args)
    if not project or not environment:
        # Help and incomplete arguments: the kernel refuses them with recovery.
        return PreflightCommand()
    from yoke_core.domain.environment_declared_facts import (
        PREFLIGHT_EXECUTOR_PATH,
        declared_text,
        settings_from_projection,
    )
    from yoke_core.domain.migration_preflight_receipt_store import read_coverage

    values, error = read_coverage(
        project=project, environment=environment, paths=[PREFLIGHT_EXECUTOR_PATH]
    )
    if error:
        return _executor_refusal(
            "fleet_preflight_executor_unreadable: could not read "
            f"{PREFLIGHT_EXECUTOR_PATH} of {project}/{environment}: {error}",
            project,
            environment,
            recovery=(
                "correct the named cause so this machine can read the "
                "environment's settings, then retry yoke watch preflight "
                "with the same arguments"
            ),
        )
    executor = declared_text(settings_from_projection(values), PREFLIGHT_EXECUTOR_PATH)
    if not executor:
        return PreflightCommand(project=project, environment=environment)
    try:
        command = shlex.split(executor)
    except ValueError as exc:
        command, detail = [], str(exc)
    else:
        detail = "it names no command"
    if not command:
        return _executor_refusal(
            f"fleet_preflight_executor_invalid: {PREFLIGHT_EXECUTOR_PATH} of "
            f"{project}/{environment} is {executor!r}, which is not a command "
            f"line ({detail})",
            project,
            environment,
            recovery="declare a valid command: " + _set_recovery(project, environment),
        )
    if local_paths:
        return _executor_refusal(
            f"fleet_preflight_executor_local_path: {project}/{environment} "
            f"runs its preflight on {executor!r}, which cannot read this "
            f"machine's {' and '.join(local_paths)}",
            project,
            environment,
            recovery=(
                f"drop {' and '.join(local_paths)} and name the source commit "
                "with --product-sha SHA; the executor rehearses that commit on "
                "its own host"
            ),
        )
    return PreflightCommand(
        executor=executor,
        words=tuple(command),
        project=project,
        environment=environment,
    )


def executor_failure(command: PreflightCommand, rc: int, raw_capture: object) -> str:
    """Name a failed or unavailable executor with its recovery."""
    from yoke_core.domain.watch_runner import WRAPPER_LAUNCH_ERROR

    outcome = (
        "could not start"
        if rc == WRAPPER_LAUNCH_ERROR
        else f"exited with code {rc}"
    )
    return compose_refusal(
        f"fleet_preflight_executor_failed: the preflight executor "
        f"{command.executor!r} declared by {command.project}/"
        f"{command.environment} release.preflight_executor {outcome}; "
        f"diagnostic capture: {raw_capture}",
        recovery=(
            "read the capture and correct the executor or the host it reaches, "
            "then retry yoke watch preflight with the same arguments. To "
            "correct the declaration: "
            + _set_recovery(command.project, command.environment)
            + " (set it empty to run the kernel on this machine)"
        ),
    )


__all__ = ["PREFLIGHT_MODULE", "PreflightCommand", "executor_failure", "resolve"]

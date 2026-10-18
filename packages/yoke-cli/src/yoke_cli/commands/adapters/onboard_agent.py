"""Which setup shell a ``yoke setup`` invocation gets, and the agent-mode run.

With a terminal, setup opens the wizard when answers are missing; with
``--non-interactive`` or ``--json`` it runs the one-shot flag path. Without a
terminal it enters agent mode: one JSON line per step, answered by later
``yoke setup --agent --answer KEY=VALUE`` calls. Setup flags given in agent
mode are presets, saved with the answers so later calls may omit them.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Callable

from yoke_cli.commands.adapters import onboard_apply
from yoke_cli.commands.adapters import onboard_hosted_authorization as hosted_auth
from yoke_cli.commands.adapters import onboard_interactive
from yoke_cli.commands.adapters import onboard_project_args
from yoke_cli.commands.adapters import onboard_resume
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_machine_setup
from yoke_cli.config import onboard_wizard
from yoke_cli.config import setup_agent_answers as answers
from yoke_cli.config import setup_agent_response as responses

SHELL_AGENT = "agent"
SHELL_WIZARD = "wizard"
SHELL_DETECT = "detect"

AGENT_ONLY_OPTIONS = frozenset({"agent", "tui", "agent_answers", "discard"})
AGENT_USAGE = "yoke setup --agent [SETUP FLAGS] [--answer KEY=VALUE ...] | --discard"


@dataclass(frozen=True)
class SetupShell:
    """The chosen shell, or the usage error or refusal that stops the run."""

    name: str = SHELL_DETECT
    error: str | None = None
    refusal: dict[str, Any] | None = None


def add_agent_args(parser: argparse.ArgumentParser) -> None:
    shell = parser.add_mutually_exclusive_group()
    shell.add_argument(
        "--agent",
        action="store_true",
        help="answer one question per call as JSON lines, for a coding agent",
    )
    shell.add_argument(
        "--tui",
        action="store_true",
        help="open the full-screen wizard; needs a terminal",
    )
    parser.add_argument(
        "--answer",
        dest="agent_answers",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="agent mode: answer the waiting question (repeat for form fields)",
    )
    parser.add_argument(
        "--discard",
        action="store_true",
        help="agent mode: delete the in-progress agent setup",
    )


def select_shell(parsed: argparse.Namespace) -> SetupShell:
    """Pick the shell from ``--agent``, ``--tui``, the one-shot flags and the terminal."""
    one_shot = parsed.non_interactive or parsed.json_mode
    agent_inputs = bool(parsed.agent_answers) or parsed.discard
    if parsed.agent:
        clashes = [
            name
            for name, given in (
                ("--non-interactive", parsed.non_interactive),
                ("--json", parsed.json_mode),
                ("--use-different-folder", bool(parsed.different_folder_run_id)),
                (
                    "TOKEN, --token-file or --token-stdin",
                    hosted_auth.has_explicit_token_source(parsed),
                ),
            )
            if given
        ]
        if clashes:
            return SetupShell(
                error=f"--agent cannot be combined with {', '.join(clashes)}"
            )
        return SetupShell(SHELL_AGENT)
    terminal = onboard_wizard.is_interactive(sys.stdin, sys.stdout)
    if parsed.tui:
        if one_shot or agent_inputs:
            return SetupShell(
                error="--tui cannot be combined with --non-interactive, --json, --answer or --discard"
            )
        if not terminal:
            return SetupShell(
                refusal=responses.refused(
                    "setup_tui_requires_terminal",
                    "run `yoke setup --tui` in a terminal, or use `yoke setup --agent`",
                    None,
                )
            )
        return SetupShell(SHELL_WIZARD)
    if one_shot or terminal or parsed.different_folder_run_id:
        if agent_inputs:
            return SetupShell(
                error="--answer and --discard belong to `yoke setup --agent`"
            )
        return SetupShell(SHELL_DETECT)
    if hosted_auth.has_explicit_token_source(parsed):
        return SetupShell(
            error=(
                "no terminal: pass --non-interactive to run setup from flags with "
                "a token, or drop the token and run `yoke setup --agent`"
            )
        )
    return SetupShell(SHELL_AGENT)


def wizard_wanted(
    parsed: argparse.Namespace,
    env_name: str,
    token_sources: list[bool],
    destination: str | None,
) -> bool:
    """Whether a terminal run is missing answers the wizard should collect."""
    if parsed.non_interactive or parsed.json_mode:
        return False
    if not onboard_wizard.is_interactive(sys.stdin, sys.stdout):
        return False
    if parsed.token_stdin:
        return False
    if destination == onboard_destinations.DESTINATION_LOCAL:
        # Local runs have no API URL or token to collect; only the project
        # answers can still be missing.
        return not parsed.project_mode or onboard_project_args.project_prompt_missing(
            parsed
        )
    return (
        not env_name
        or not parsed.api_url
        or not any(token_sources)
        or not parsed.project_mode
        or onboard_project_args.project_prompt_missing(parsed)
    )


def run(
    parsed: argparse.Namespace,
    *,
    defaults: argparse.Namespace,
) -> int:
    """Run one agent-mode invocation; ``defaults`` is the parse of no flags."""
    try:
        cli_answers = _cli_answers(parsed.agent_answers or [])
    except ValueError as exc:
        return _usage(str(exc))
    if parsed.discard:
        if cli_answers:
            return _usage("--discard cannot be combined with --answer")
        return _discard()
    try:
        store = answers.open_store()
    except answers.AnswerStoreError as exc:
        return _refuse(exc.reason, str(exc))
    try:
        refusal = _apply_presets(parsed, defaults, store)
        if refusal is not None:
            cli_answers = {}
        prepared = onboard_resume.prepare_run(parsed)
        if prepared.error:
            return _usage(prepared.error)
        onboard_machine_setup.prepare(machine_config.config_path(parsed.config_path))
        selected_mode = "advanced" if parsed.advanced else "quick"
        setup = _agent_setup()(
            defaults=onboard_interactive.wizard_defaults(
                parsed, prepared.env_name, selected_mode, prepared.destination
            ),
            apply_report=onboard_interactive.report_runner(
                parsed, onboard_apply.apply_with_durable_report, install_health=True
            ),
            store=store,
            cli_answers=cli_answers,
            refusal=refusal,
        )
        code = setup.run()
    except KeyboardInterrupt:
        responses.emit(responses.interrupted())
        return responses.EXIT_CODES[responses.STATE_FAILED]
    except Exception as exc:  # noqa: BLE001 - agent mode never prints a traceback
        responses.emit(
            responses.failed(
                "setup_step_failed",
                f"{type(exc).__name__}: {exc}. Fix the named cause, then run "
                "`yoke setup --agent` again.",
            )
        )
        return responses.EXIT_CODES[responses.STATE_FAILED]
    finally:
        store.release()
    if setup.outcome == responses.STATE_DONE:
        onboard_interactive.finish_pending_source_install(
            parsed.config_path, stream=sys.stderr
        )
    return code


def _apply_presets(
    parsed: argparse.Namespace,
    defaults: argparse.Namespace,
    store: answers.AnswerStore,
) -> tuple[str, str] | None:
    """Save this run's presets, or keep the stored ones and name the change."""
    given = {
        name: value
        for name, value in vars(parsed).items()
        if name not in AGENT_ONLY_OPTIONS and value != getattr(defaults, name, None)
    }
    refusal = None
    if not store.existed:
        store.presets = given
    elif given and given != store.presets:
        refusal = (
            "setup_agent_flags_changed",
            "these setup flags differ from the ones this setup started with; "
            "rerun with only --agent and --answer, or run `yoke setup --agent "
            "--discard` to start over with the new flags",
        )
    for name, value in store.presets.items():
        setattr(parsed, name, value)
    return refusal


def _cli_answers(pairs: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        key = key.strip()
        if not sep or not key:
            raise ValueError(f"--answer takes KEY=VALUE, not {pair!r}")
        if key in found:
            raise ValueError(f"--answer {key} was given twice")
        found[key] = value
    return found


def _discard() -> int:
    try:
        removed = answers.discard_saved()
    except answers.AnswerStoreError as exc:
        return _refuse(exc.reason, str(exc))
    detail = (
        "The in-progress agent setup was deleted."
        if removed
        else "There was no in-progress agent setup to delete."
    )
    responses.emit(
        responses.response(
            responses.STATE_DONE,
            discarded=removed,
            detail=[detail],
            next=["Run `yoke setup --agent` to start again."],
        )
    )
    return 0


def _agent_setup() -> Callable[..., Any]:
    from yoke_cli.config.setup_agent_shell import AgentSetup

    return AgentSetup


def _refuse(reason: str, recovery: str) -> int:
    responses.emit(responses.refused(reason, recovery, None))
    return responses.EXIT_CODES[responses.STATE_REFUSED]


def _usage(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    print(f"Usage: {AGENT_USAGE}", file=sys.stderr)
    return 2


__all__ = [
    "SHELL_AGENT",
    "SHELL_DETECT",
    "SHELL_WIZARD",
    "SetupShell",
    "add_agent_args",
    "run",
    "select_shell",
    "wizard_wanted",
]

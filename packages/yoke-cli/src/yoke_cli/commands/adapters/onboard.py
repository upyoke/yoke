"""Machine and project onboarding adapter for ``yoke setup``."""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.adapters import onboard_agent
from yoke_cli.commands.adapters import onboard_apply
from yoke_cli.commands.adapters import onboard_destination_args
from yoke_cli.commands.adapters import onboard_hosted_authorization as hosted_auth
from yoke_cli.commands.adapters import onboard_interactive
from yoke_cli.commands.adapters import onboard_project_args
from yoke_cli.commands.adapters import onboard_resume
from yoke_cli.commands.adapters.onboard_github_requests import (
    github_user_access_token as _github_user_access_token,
    project_clone as _project_clone,
    project_needs_github_user_access_token as _project_needs_github_user_access_token,
    project_publish as _project_publish,
)
from yoke_cli.config import machine_config
from yoke_contracts import harness_unattended_posture
from yoke_cli.commands.adapters.onboard_build_report import (
    MachineConfigWriteError,  # noqa: F401 — re-exported adapter surface
    build_report as _build_report,  # module global, so a test can patch it
)
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config import github_user_tokens
from yoke_cli.config import setup_agent_response


ONBOARD_USAGE = (
    "yoke setup [--agent [--answer KEY=VALUE ...] | --tui] | "
    "yoke setup --agent --discard | "
    "yoke setup [--quick | --advanced] [--local | --connect URL] [--json] "
    "[--non-interactive] [--config PATH] --env ENV --api-url URL "
    "[TOKEN | --token-file PATH | --token-stdin] [--yes] "
    "[--machine-github connect|disabled] "
    "[--skip-identity-check] "
    "[--project-mode machine-only|create-repo|clone-remote|import-remote|"
    "local-checkout --checkout PATH [--remote-url URL] "
    "--project-slug SLUG --project-name NAME --default-branch BRANCH "
    "--public-item-prefix PREFIX [--github-repo OWNER/REPO] "
    "[--github-adoption app-binding|disabled]]"
)


def onboard(args: List[str]) -> int:
    parsed = parse_or_usage_error(_parser(), args, ONBOARD_USAGE)
    if parsed is None:
        return 2
    shell = onboard_agent.select_shell(parsed)
    if shell.error:
        print(f"error: {shell.error}", file=sys.stderr)
        print(f"Usage: {ONBOARD_USAGE}", file=sys.stderr)
        return 2
    if shell.refusal:
        setup_agent_response.emit(shell.refusal)
        return 2
    if shell.name == onboard_agent.SHELL_AGENT:
        return onboard_agent.run(parsed, defaults=_parser().parse_args([]))
    return _run_flags_or_wizard(parsed, force_wizard=shell.name == onboard_agent.SHELL_WIZARD)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter, prog="yoke setup"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="Quick setup (the default).")
    mode.add_argument("--advanced", action="store_true", help="Ask about each choice.")
    onboard_destination_args.add_destination_args(parser)
    add = parser.add_argument
    add("--json", dest="json_mode", action="store_true", help="Print JSON output.")
    add("--non-interactive", action="store_true", help="Never prompt; use flags only.")
    add("--config", dest="config_path", metavar="PATH", help="Machine config file.")
    add("--env", dest="env_name", metavar="ENV", help="Connection name to set up.")
    add("--api-url", dest="api_url", metavar="URL", help="Yoke API URL to connect to.")
    hosted_auth.add_token_arguments(parser)
    add("--yes", dest="apply", action="store_true", help="Apply instead of preview.")
    parser.add_argument(
        "--machine-github",
        choices=("connect", "disabled"),
        default=None,
        help="Connect the advertised Yoke GitHub App or stay disabled.",
    )
    parser.add_argument(
        "--skip-identity-check",
        dest="skip_identity_check",
        action="store_true",
        help="Skip confirming the signed-in identity after connecting.",
    )
    parser.add_argument(
        "--post-install",
        dest="post_install",
        action="store_true",
        help="Launched straight after install; run the install checks automatically.",
    )
    parser.add_argument(
        "--skip-harness-permissions",
        dest="harness_posture",
        action="store_false",
        help=harness_unattended_posture.POSTURE_DECLINE_HELP,
    )
    add(
        "--resume",
        dest="resume_run_id",
        metavar="RUN-ID",
        help="Resume the setup run with this id.",
    )
    parser.add_argument(
        "--use-different-folder",
        dest="different_folder_run_id",
        default=None,
        metavar="RUN-ID",
        help=(
            "Keep a failed run's checkout and close that run, then choose a "
            "different folder. --start-over RUN-ID is an older name for this flag."
        ),
    )
    # Older name kept working; hidden so the page names one flag.
    parser.add_argument(
        "--start-over", dest="different_folder_run_id", help=argparse.SUPPRESS
    )
    onboard_project_args.add_project_args(parser)
    onboard_agent.add_agent_args(parser)
    return parser


def _run_flags_or_wizard(parsed: argparse.Namespace, *, force_wizard: bool) -> int:
    explicit_token_source = hosted_auth.has_explicit_token_source(parsed)
    if parsed.resume_run_id and parsed.different_folder_run_id:
        print(
            "error: --resume and --use-different-folder cannot be used together",
            file=sys.stderr,
        )
        return 2
    if parsed.different_folder_run_id:
        return onboard_resume.use_different_folder(
            parsed.different_folder_run_id,
            confirmed=parsed.apply,
            json_mode=parsed.json_mode,
        )
    prepared = onboard_resume.prepare_run(parsed)
    if prepared.error:
        print(f"error: {prepared.error}", file=sys.stderr)
        return 2
    destination, env_name = prepared.destination, prepared.env_name
    reused_connection = prepared.reused_connection
    local_destination = destination == onboard_destinations.DESTINATION_LOCAL
    selected_mode = "advanced" if parsed.advanced else "quick"
    config_path = str(machine_config.config_path(parsed.config_path))
    missing = onboard_destination_args.missing_required_flags(
        parsed,
        env_name=env_name,
        local_destination=local_destination,
    )
    token_sources = onboard_destination_args.token_sources(parsed)
    should_prompt = force_wizard or onboard_agent.wizard_wanted(
        parsed, env_name, token_sources, destination
    )
    hosted_usage_error = hosted_auth.usage_error(
        destination,
        explicit_token_source,
        bool(parsed.resume_run_id) or reused_connection,
        should_prompt,
    )
    if hosted_usage_error:
        print(f"error: {hosted_usage_error}", file=sys.stderr)
        return 2
    if should_prompt:
        if sum(1 for given in token_sources if given) > 1:
            print(
                "error: exactly one token source is required",
                file=sys.stderr,
            )
            print(f"Usage: {ONBOARD_USAGE}", file=sys.stderr)
            return 2
        return _run_wizard(parsed, env_name, selected_mode, destination)
    if missing:
        print(
            f"error: missing required onboarding flags: {', '.join(missing)}; "
            "run `yoke setup --agent` to be asked for each missing answer",
            file=sys.stderr,
        )
        print(f"Usage: {ONBOARD_USAGE}", file=sys.stderr)
        return 2
    if not local_destination and sum(1 for given in token_sources if given) != 1:
        print(
            "error: exactly one token source is required",
            file=sys.stderr,
        )
        print(f"Usage: {ONBOARD_USAGE}", file=sys.stderr)
        return 2
    token = parsed.token
    token_source_kind = "argument"
    if parsed.token_stdin:
        token = sys.stdin.read().strip()
        token_source_kind = "stdin"
        if not token:
            print("error: token on stdin is empty", file=sys.stderr)
            return 2
    requested_machine_github = getattr(parsed, "machine_github", None)
    connect_machine_github = requested_machine_github == "connect"
    use_machine_github = connect_machine_github or bool(
        getattr(parsed, "project_clone_use_machine_github", False)
    )
    machine_github_choice = (
        "connect"
        if requested_machine_github == "connect"
        else "skip"
        if requested_machine_github == "disabled"
        else getattr(parsed, "machine_github_choice", None) or "skip"
    )
    try:
        needs_user_token = _project_needs_github_user_access_token(parsed)
        github_user_access_token = _github_user_access_token(
            parsed,
            required=needs_user_token and not connect_machine_github,
            local_connection_selected=local_destination,
        )
        project_publish = _project_publish(
            parsed,
            github_user_access_token,
            use_machine_github=use_machine_github,
        )
        project_clone = _project_clone(
            parsed,
            github_user_access_token,
            project_publish,
            use_machine_github=use_machine_github,
        )
    except github_user_tokens.GitHubUserTokenError:
        print(
            "error: GitHub App user authorization is unavailable. Run `yoke "
            "github connect` and retry, or continue disabled.",
            file=sys.stderr,
        )
        return 2
    report = _build_report(
        config_path=config_path,
        env_name=env_name,
        api_url=parsed.api_url or "",
        destination=destination or onboard_destinations.DEFAULT_DESTINATION,
        admin_name=getattr(parsed, "admin_name", None),
        token=token,
        token_file=parsed.token_file,
        token_source_kind=token_source_kind,
        mode=selected_mode,
        apply=parsed.apply,
        check_identity=not parsed.skip_identity_check,
        machine_github_choice=machine_github_choice,
        machine_github_api_url=getattr(parsed, "machine_github_api_url", None),
        project_mode=parsed.project_mode or onboard_config.PROJECT_MODE_MACHINE_ONLY,
        project_remote_url=parsed.project_remote_url,
        project_checkout=parsed.project_checkout,
        project_slug=parsed.project_slug,
        project_name=parsed.project_name,
        project_org=parsed.project_org,
        project_github_repo=parsed.project_github_repo,
        project_github_repository_id=getattr(
            parsed,
            "project_github_repository_id",
            None,
        ),
        project_github_installation_id=getattr(
            parsed,
            "project_github_installation_id",
            None,
        ),
        project_default_branch=parsed.project_default_branch,
        project_default_branch_source=(
            getattr(parsed, "project_default_branch_source", None)
        ),
        project_public_item_prefix=parsed.project_public_item_prefix,
        existing_project_id=getattr(parsed, "existing_project_id", None),
        existing_project_match_source=getattr(
            parsed,
            "existing_project_match_source",
            None,
        ),
        existing_project_local_source=getattr(
            parsed,
            "existing_project_local_source",
            None,
        ),
        project_github_adoption=parsed.github_adoption,
        project_github_adoption_preserve=bool(
            getattr(parsed, "project_github_adoption_preserve", False)
        ),
        project_publish=project_publish,
        project_clone=project_clone,
        project_keep_existing_remote=bool(
            getattr(parsed, "project_keep_existing_remote", False)
        ),
        resume_run_id=parsed.resume_run_id,
        resume_payload=parsed.resume_payload,
        harness_posture=bool(getattr(parsed, "harness_posture", True)),
    )
    if report is None:
        return 1
    if parsed.json_mode:
        print(onboard_config.dumps_json(report), end="")
    else:
        print(onboard_config.render_human(report), end="")
    if parsed.apply:
        _finish_pending_dev_install(
            parsed.config_path,
            stream=sys.stderr if parsed.json_mode else sys.stdout,
        )
    return 0


def _run_wizard(
    parsed: argparse.Namespace,
    env_name: str,
    selected_mode: str,
    destination: str | None,
) -> int:
    return onboard_interactive.run_wizard(
        parsed,
        env_name,
        selected_mode,
        destination,
        apply_with_report=_apply_with_durable_report,
        print_failure=_print_failure_summary,
    )


_finish_pending_dev_install = onboard_interactive.finish_pending_source_install

_apply_with_durable_report = onboard_apply.apply_with_durable_report
_print_failure_summary = onboard_apply.print_failure_summary


__all__ = ["ONBOARD_USAGE", "onboard"]

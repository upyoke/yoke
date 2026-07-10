"""Machine and project onboarding adapter for ``yoke onboard``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from yoke_contracts import github_origin
from yoke_cli.commands._helpers import (
    attach_field_note_footer,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters import onboard_apply
from yoke_cli.commands.adapters import onboard_destination_args
from yoke_cli.commands.adapters import onboard_project_args
from yoke_cli.commands.adapters import onboard_resume
from yoke_cli.config import machine_config
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_apply_resume
from yoke_cli.config import onboard_wizard
from yoke_cli.config import github_user_tokens
from yoke_cli.config import yoke_dev_access
from yoke_cli.config.onboard_error_friendly import friendly_permission_error
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_MAKE_IT_MINE,
    ClonePlan,
)
from yoke_cli.config.project_publish_support import PublishRequest
from yoke_cli.config.writer import MachineConfigWriteError
from yoke_contracts.machine_config.schema import MachineConfigContractError


ONBOARD_USAGE = (
    "yoke onboard [--quick | --advanced] [--local | --connect URL] [--json] "
    "[--non-interactive] [--config PATH] --env ENV --api-url URL "
    "[TOKEN | --token-file PATH | --token-stdin] [--yes] "
    "[--skip-identity-check] "
    "[--project-mode machine-only|create-repo|clone-remote|import-remote|"
    "local-checkout --checkout PATH [--remote-url URL] "
    "--project-slug SLUG --project-name NAME --default-branch BRANCH "
    "--public-item-prefix PREFIX [--github-repo OWNER/REPO] "
    "[--github-adoption app-binding|backlog-only]]"
)


def onboard(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke onboard")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true")
    mode.add_argument("--advanced", action="store_true")
    onboard_destination_args.add_destination_args(parser)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--config", dest="config_path", default=None, metavar="PATH")
    parser.add_argument("--env", dest="env_name", default=None)
    parser.add_argument("--api-url", dest="api_url", default=None)
    parser.add_argument("token", nargs="?")
    parser.add_argument("--token-file", dest="token_file", default=None)
    parser.add_argument("--token-stdin", dest="token_stdin",
                        action="store_true")
    parser.add_argument("--yes", dest="apply", action="store_true")
    parser.add_argument(
        "--skip-identity-check", dest="skip_identity_check",
        action="store_true",
    )
    parser.add_argument(
        "--post-install", dest="post_install", action="store_true",
        help="launched straight after install; show the install-summary screen",
    )
    parser.add_argument("--resume", dest="resume_run_id", default=None)
    parser.add_argument("--start-over", dest="start_over_run_id", default=None)
    onboard_project_args.add_project_args(parser)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, ONBOARD_USAGE)
    if parsed is None:
        return 2
    if parsed.resume_run_id and parsed.start_over_run_id:
        print("error: --resume and --start-over cannot be used together", file=sys.stderr)
        return 2
    if parsed.start_over_run_id:
        return onboard_resume.start_over(
            parsed.start_over_run_id,
            confirmed=parsed.apply,
            json_mode=parsed.json_mode,
        )
    parsed.resume_payload = None
    if parsed.resume_run_id:
        try:
            parsed.resume_payload = onboard_apply_resume.load_payload(
                parsed.resume_run_id
            )
            snapshot = onboard_apply_resume.load_snapshot(parsed.resume_run_id)
            onboard_apply_resume.apply_defaults(parsed, snapshot)
        except onboard_apply_resume.OnboardApplyResumeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    choice = onboard_destination_args.resolve_destination(parsed)
    if choice.error:
        print(f"error: {choice.error}", file=sys.stderr)
        return 2
    destination = choice.destination
    env_name = choice.env_name
    local_destination = destination == onboard_destinations.DESTINATION_LOCAL
    selected_mode = "advanced" if parsed.advanced else "quick"
    config_path = str(machine_config.config_path(parsed.config_path))
    missing = [] if local_destination else [
        flag for flag, value in (
            ("--env", env_name),
            ("--api-url", parsed.api_url),
        )
        if not value
    ]
    token_sources = [
        bool(parsed.token),
        bool(parsed.token_file),
        bool(parsed.token_stdin),
    ]
    if _should_prompt(parsed, env_name, token_sources, destination):
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
            f"error: missing required onboarding flags: {', '.join(missing)}",
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
    machine_github_choice = getattr(parsed, "machine_github_choice", None) or "skip"
    try:
        needs_user_token = _project_needs_github_user_access_token(parsed)
        github_user_access_token = _github_user_access_token(
            parsed,
            required=needs_user_token,
        )
        project_publish = _project_publish(parsed, github_user_access_token)
        project_clone = _project_clone(
            parsed, github_user_access_token, project_publish,
        )
    except github_user_tokens.GitHubUserTokenError:
        print(
            "error: GitHub App user authorization is unavailable. Run `yoke "
            "github connect` and retry, or continue backlog-only.",
            file=sys.stderr,
        )
        return 2
    # The legacy flag lane (--api-url without --local/--connect) reaches
    # here with no resolved destination; the URL itself names one. Deriving
    # it keeps the report and resume snapshot truthful — a resumed run must
    # preset the server lane for a team-server URL, not the hosted default.
    if destination is None and parsed.api_url:
        destination = onboard_destinations.destination_for_api_url(
            parsed.api_url
        )
    source_dev_defaults = _source_dev_project_defaults(parsed.project_mode)
    report = _build_report(
        config_path=config_path,
        env_name=env_name,
        api_url=parsed.api_url or "",
        destination=destination or onboard_destinations.DEFAULT_DESTINATION,
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
        project_slug=parsed.project_slug or source_dev_defaults.get("slug"),
        project_name=parsed.project_name or source_dev_defaults.get("name"),
        project_org=parsed.project_org,
        project_github_repo=(
            parsed.project_github_repo or source_dev_defaults.get("github_repo")
        ),
        project_default_branch=(
            parsed.project_default_branch or source_dev_defaults.get("default_branch")
        ),
        project_default_branch_source=(
            getattr(parsed, "project_default_branch_source", None)
        ),
        project_public_item_prefix=(
            parsed.project_public_item_prefix
            or source_dev_defaults.get("public_item_prefix")
        ),
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
        project_publish=project_publish,
        project_clone=project_clone,
        project_keep_existing_remote=bool(
            getattr(parsed, "project_keep_existing_remote", False)
        ),
        resume_run_id=parsed.resume_run_id,
        resume_payload=parsed.resume_payload,
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


def _source_dev_project_defaults(project_mode: str | None) -> dict[str, str]:
    if project_mode != onboard_config.PROJECT_MODE_SOURCE_DEV_ADMIN:
        return {}
    return {
        "slug": yoke_dev_access.YOKE_PROJECT_SLUG,
        "name": yoke_dev_access.YOKE_PROJECT_NAME,
        "github_repo": yoke_dev_access.YOKE_GITHUB_REPO,
        "default_branch": yoke_dev_access.YOKE_DEFAULT_BRANCH,
        "public_item_prefix": yoke_dev_access.YOKE_PUBLIC_ITEM_PREFIX,
    }


def _should_prompt(
    parsed: argparse.Namespace,
    env_name: str,
    token_sources: list[bool],
    destination: str | None,
) -> bool:
    if parsed.non_interactive or parsed.json_mode:
        return False
    if not onboard_wizard.is_interactive(sys.stdin, sys.stdout):
        return False
    if parsed.token_stdin:
        return False
    return _has_missing_prompt_input(parsed, env_name, token_sources, destination)


def _has_missing_prompt_input(
    parsed: argparse.Namespace,
    env_name: str,
    token_sources: list[bool],
    destination: str | None,
) -> bool:
    if destination == onboard_destinations.DESTINATION_LOCAL:
        # Local runs have no API URL or token to collect; only the project
        # answers can still be missing.
        return (
            not parsed.project_mode
            or onboard_project_args.project_prompt_missing(parsed)
        )
    return (
        not env_name
        or not parsed.api_url
        or not any(token_sources)
        or not parsed.project_mode
        or onboard_project_args.project_prompt_missing(parsed)
    )


def _run_wizard(
    parsed: argparse.Namespace,
    env_name: str,
    selected_mode: str,
    destination: str | None,
) -> int:
    """Launch the full-screen Textual wizard; apply on a single confirm."""
    defaults = onboard_wizard.WizardDefaults(
        config_path=str(machine_config.config_path(parsed.config_path)),
        env_name=env_name or None,
        api_url=parsed.api_url,
        destination=destination,
        token=parsed.token,
        token_file=parsed.token_file,
        mode=selected_mode if (parsed.quick or parsed.advanced) else None,
        project_mode=parsed.project_mode,
        project_checkout=parsed.project_checkout,
        apply=parsed.apply,
        post_install=parsed.post_install,
    )
    def apply_report(kwargs: dict, tui_progress=None) -> dict:
        if parsed.skip_identity_check:
            kwargs = {**kwargs, "check_identity": False}
        if parsed.resume_run_id:
            kwargs = {
                **kwargs,
                "resume_run_id": parsed.resume_run_id,
                "resume_payload": parsed.resume_payload,
            }
        return _apply_with_durable_report(kwargs, tui_progress=tui_progress)

    try:
        result = onboard_wizard.run_wizard(defaults, apply_report=apply_report)
    except onboard_wizard.WizardCancelled as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if result.error:
        _print_failure_summary(result)
        return 1
    _finish_pending_dev_install(parsed.config_path)
    return result.exit_code


def _finish_pending_dev_install(config_path: str | None, *, stream=None) -> None:
    """Run the deferred "Develop Yoke itself" editable install AFTER the wizard UI
    has closed.

    ``uv pip install -e`` deletes the product wheel this process runs from, so
    everything here stays plain stdlib (print) — never touch yoke_cli after the
    editable install. dev_setup + project_onboard_apply are imported lazily so the
    adapter's import order can't matter.
    """
    from yoke_cli.config import dev_setup
    from yoke_cli.config import project_onboard_apply

    stream = stream or sys.stdout
    root = project_onboard_apply.pop_pending_dev_install(config_path)
    if not root:
        return
    print(
        "\nFinalizing the Yoke dev install (pointing `yoke` at this checkout)…",
        file=stream,
    )
    outcome = dev_setup.run_editable_install_step(Path(root))
    if outcome.get("ok"):
        print(
            f"✓ Dev environment ready. Open a new terminal so `yoke` runs "
            f"from {root}.",
            file=stream,
        )
    else:
        print(f"⚠ Couldn't finish the dev install: {outcome.get('error')}", file=stream)
        print(
            f"  Finish it with: yoke dev setup {root} --editable-install --yes",
            file=stream,
        )


def _build_report(
    *,
    config_path: str | None,
    env_name: str,
    api_url: str,
    destination: str = onboard_destinations.DEFAULT_DESTINATION,
    token: str | None,
    token_file: str | None,
    token_source_kind: str,
    mode: str,
    apply: bool,
    check_identity: bool,
    machine_github_choice: str,
    machine_github_api_url: str | None,
    project_mode: str,
    project_remote_url: str | None,
    project_checkout: str | None,
    project_slug: str | None,
    project_name: str | None,
    project_org: str | None,
    project_github_repo: str | None,
    project_default_branch: str | None,
    project_default_branch_source: str | None,
    project_public_item_prefix: str | None,
    existing_project_id: int | None,
    project_github_adoption: str | None,
    existing_project_match_source: str | None = None,
    existing_project_local_source: str | None = None,
    project_publish: PublishRequest | None = None,
    project_clone: ClonePlan | None = None,
    project_keep_existing_remote: bool = False,
    resume_run_id: str | None = None,
    resume_payload: dict | None = None,
) -> dict | None:
    try:
        return _apply_with_durable_report({
            "config_path": config_path,
            "env_name": env_name,
            "api_url": api_url,
            "destination": destination,
            "token": token,
            "token_file": token_file,
            "token_source_kind": token_source_kind,
            "mode": mode,
            "apply": apply,
            "check_identity": check_identity,
            "machine_github_choice": machine_github_choice,
            "machine_github_api_url": machine_github_api_url,
            "project_mode": project_mode,
            "project_remote_url": project_remote_url,
            "project_checkout": project_checkout,
            "project_slug": project_slug,
            "project_name": project_name,
            "project_org": project_org,
            "project_github_repo": project_github_repo,
            "project_default_branch": project_default_branch,
            "project_default_branch_source": project_default_branch_source,
            "project_public_item_prefix": project_public_item_prefix,
            "existing_project_id": existing_project_id,
            "existing_project_match_source": existing_project_match_source,
            "existing_project_local_source": existing_project_local_source,
            "project_github_adoption": project_github_adoption,
            "project_publish": project_publish,
            "project_clone": project_clone,
            "project_keep_existing_remote": project_keep_existing_remote,
            "resume_run_id": resume_run_id,
            "resume_payload": resume_payload,
        })
    except (
        onboard_config.OnboardError,
        onboard_apply_report.OnboardApplyReportError,
        MachineConfigContractError,
        MachineConfigWriteError,
    ) as exc:
        print(f"error: {friendly_permission_error(str(exc))}", file=sys.stderr)
        return None
    except onboard_wizard.WizardApplyError as exc:
        _print_failure_summary(onboard_wizard.WizardRunResult(
            exit_code=1,
            error=str(exc),
            failed_step=exc.failed_step,
            report_path=exc.report_path,
            resume_command=exc.resume_command,
        ))
        return None


_apply_with_durable_report = onboard_apply.apply_with_durable_report
_print_failure_summary = onboard_apply.print_failure_summary


def _github_user_access_token(
    parsed: argparse.Namespace,
    *,
    required: bool,
) -> str | None:
    if not required:
        return None
    refreshed = github_user_tokens.access_token_from_machine_config(
        config_path=getattr(parsed, "config_path", None),
    )
    return refreshed.access_token


def _project_publish(
    parsed: argparse.Namespace,
    github_user_access_token: str | None,
) -> PublishRequest | None:
    owner = str(getattr(parsed, "project_publish_owner", "") or "").strip()
    name = str(getattr(parsed, "project_publish_repo_name", "") or "").strip()
    if not (owner and name):
        return None
    if not github_user_access_token:
        raise github_user_tokens.GitHubUserTokenError(
            "GitHub App user authorization is required to create a GitHub repo. "
            "Run `yoke github connect` when browser authorization is available, "
            "or continue backlog-only."
        )
    return PublishRequest(
        owner=owner,
        name=name,
        user_login=str(getattr(parsed, "project_publish_owner_login", "") or ""),
        token=github_user_access_token,
        api_url=str(
            getattr(parsed, "project_publish_api_url", "")
            or getattr(parsed, "machine_github_api_url", "")
            or github_origin.DEFAULT_GITHUB_API_URL
        ),
        private=bool(getattr(parsed, "project_publish_private", True)),
        administration_allowed=_github_administration_allowed(
            getattr(parsed, "config_path", None), owner,
        ),
        web_url=_github_web_url(getattr(parsed, "config_path", None)),
    )


def _project_clone(
    parsed: argparse.Namespace,
    github_user_access_token: str | None,
    project_publish: PublishRequest | None,
) -> ClonePlan | None:
    outcome = str(getattr(parsed, "project_clone_outcome", "") or "").strip()
    if not outcome:
        if github_user_access_token and str(
            getattr(parsed, "project_mode", "") or ""
        ) in ("clone-remote", "import-remote"):
            return ClonePlan(
                fallback_token=github_user_access_token,
                fork_web_url=_github_web_url(getattr(parsed, "config_path", None)),
            )
        return None
    if outcome in (CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE):
        if not github_user_access_token:
            raise github_user_tokens.GitHubUserTokenError(
                "GitHub App user authorization is required for the saved clone "
                "outcome. Run `yoke github connect` when browser authorization "
                "is available, or choose a plain clone/backlog-only flow."
            )
    return ClonePlan(
        outcome=outcome,
        keep_upstream=bool(getattr(parsed, "project_clone_keep_upstream", True)),
        publish=project_publish if outcome == CLONE_OUTCOME_MAKE_IT_MINE else None,
        fallback_token=github_user_access_token,
        fork_api_url=str(
            getattr(parsed, "project_clone_fork_api_url", "")
            or getattr(parsed, "machine_github_api_url", "")
            or github_origin.DEFAULT_GITHUB_API_URL
        ),
        fork_web_url=_github_web_url(getattr(parsed, "config_path", None)),
    )


def _project_needs_github_user_access_token(parsed: argparse.Namespace) -> bool:
    outcome = str(getattr(parsed, "project_clone_outcome", "") or "").strip()
    if outcome in (CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE):
        return True
    if str(getattr(parsed, "project_mode", "") or "") in (
        "clone-remote", "import-remote",
    ):
        return bool(machine_config.github_config(getattr(parsed, "config_path", None)))
    return bool(
        str(getattr(parsed, "project_publish_owner", "") or "").strip()
        and str(getattr(parsed, "project_publish_repo_name", "") or "").strip()
    )


def _github_administration_allowed(config_path: str | None, owner: str) -> bool:
    github = machine_config.github_config(config_path)
    return any(
        isinstance(installation, dict)
        and isinstance(installation.get("permissions"), dict)
        and str(installation.get("account_login") or "").casefold() == owner.casefold()
        and not installation.get("suspended")
        and installation["permissions"].get("administration") == "write"
        for installation in github.get("installations") or []
    )


def _github_web_url(config_path: str | None) -> str:
    github = machine_config.github_config(config_path)
    return github_origin.validate_github_web_endpoint(
        str(github.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL)
    ).base_url


__all__ = ["ONBOARD_USAGE", "onboard"]

"""``yoke project git bootstrap`` — client-local git init and private remote."""

from __future__ import annotations

from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.project_git_bootstrap import GIT_BOOTSTRAP_USAGE


PROJECT_GIT_BOOTSTRAP_USAGE = GIT_BOOTSTRAP_USAGE

USAGE_BY_FUNCTION_ID = {
    "project.git.bootstrap": PROJECT_GIT_BOOTSTRAP_USAGE,
}


def project_git_bootstrap(args: List[str]) -> int:
    parser = _parser()
    parsed = parse_or_usage_error(parser, args, PROJECT_GIT_BOOTSTRAP_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        text = result.get("text")
        if text:
            print(text, file=stdout)
        return None

    payload: Dict[str, Any] = {
        "checkout": parsed.checkout,
        "init_repo": parsed.init_repo,
        "create_remote": parsed.create_remote,
        "default_branch": parsed.default_branch,
        "apply": parsed.apply,
    }
    if parsed.project is not None:
        payload["project"] = parsed.project
    if parsed.owner is not None:
        payload["owner"] = parsed.owner
    if parsed.name is not None:
        payload["name"] = parsed.name
    if parsed.config_path is not None:
        payload["config_path"] = parsed.config_path
    return dispatch_and_emit(
        function_id="project.git.bootstrap",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
        local_only=True,
    )


def _parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="yoke project git bootstrap",
        description=(
            "Init a checkout (starter .gitignore + initial commit) and "
            "optionally create a private GitHub repository, add origin, "
            "push, and bind the project. Default is dry-run; pass --yes "
            "to apply. Existing remotes are never replaced."
        ),
    )
    parser.add_argument("checkout")
    parser.add_argument(
        "--no-init", dest="init_repo", action="store_false",
        help="Do not git init; refuse if the checkout is not already a repo.",
    )
    parser.add_argument(
        "--no-create-remote", dest="create_remote", action="store_false",
        help="Skip GitHub repository creation, origin, push, and binding.",
    )
    add_project_arg(parser)
    parser.add_argument("--owner", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument(
        "--default-branch", dest="default_branch", default="main",
    )
    parser.add_argument("--config", dest="config_path", default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--yes", dest="apply", action="store_true")
    mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.set_defaults(
        init_repo=True, create_remote=True, apply=False, dry_run=False,
    )
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


__all__ = [
    "PROJECT_GIT_BOOTSTRAP_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "project_git_bootstrap",
]

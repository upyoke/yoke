"""Project checkout registration CLI adapter.

Split from :mod:`yoke_cli.commands.adapters.config_write` under the
authored-file line cap; re-exported there so existing imports are unaffected.
"""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    call_dispatcher,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.config_write_shared import run
from yoke_cli.config import writer
from yoke_contracts.api.function_call import TargetRef

REASSIGN_ACTION = (
    "Moving a registered project's checkout (yoke project register --reassign)"
)

PROJECT_REGISTER_USAGE = (
    "yoke project register REPO_ROOT --project-id N "
    "[--board-scope SCOPE] [--board-render-path PATH] [--reassign] "
    "[--config PATH]"
)


def project_register(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke project register",
        description=(
            "Map one machine-local checkout to a project id, scoped to the selected connection.\n"
            "Moving a project id already routed elsewhere needs --reassign."
        ),
    )
    parser.add_argument("repo_root")
    parser.add_argument("--project-id", dest="project_id", type=int, required=True)
    parser.add_argument("--board-scope", dest="board_scope", default=None)
    parser.add_argument("--board-render-path", dest="board_render_path", default=None)
    parser.add_argument(
        "--reassign",
        action="store_true",
        default=False,
        help=(
            "Deliberate checkout move; requires this session's live steering "
            "seat on the project."
        ),
    )
    parser.add_argument("--config", dest="config_path", default=None)
    parsed = parse_or_usage_error(parser, args, PROJECT_REGISTER_USAGE)
    if parsed is None:
        return 2

    def _register() -> dict:
        if parsed.reassign:
            require_reassign_seat(parsed.project_id)
        return writer.register_project(
            parsed.repo_root,
            parsed.project_id,
            board_scope=parsed.board_scope,
            board_render_path=parsed.board_render_path,
            reassign=parsed.reassign,
            path=parsed.config_path,
        )

    return run(_register)


def require_reassign_seat(project_id: int) -> None:
    """Refuse a checkout move unless the control plane confirms the seat."""
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="claims.steering.verify",
        target=TargetRef(kind="global", project_id=str(project_id)),
        payload={"action": REASSIGN_ACTION},
    )
    if response.success:
        return
    error = response.error
    raise writer.MachineConfigWriteError(
        f"{error.code}: {error.message}"
        if error is not None
        else "steering_verify_failed: the control plane gave no answer; "
        "run yoke claims steering verify --project "
        f"{project_id} to diagnose, then retry"
    )


__all__ = ["PROJECT_REGISTER_USAGE", "project_register", "require_reassign_seat"]

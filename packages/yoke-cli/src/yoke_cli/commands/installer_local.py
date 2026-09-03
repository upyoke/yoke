"""Tool-shaped (client-local) installer / onboarding commands.

These run on the caller's own machine — machine config, git, dev setup,
project source creation — and carry NO dispatcher function id. Like the
git-hook bodies, they route via the tool-shaped table after SUBCOMMAND_REGISTRY
misses (see ``tool_shaped.resolve_tool_shaped``). Per the command-surface
ratchet, agent-facing operations are wrapped as dispatcher functions; these are
deliberately client-local CLI commands instead, so the fallback-registry
coherence check does not expect a registered handler behind them.
"""

from __future__ import annotations

from typing import Dict, Tuple

from yoke_cli.commands.adapters.aws import (
    aws_admin_link,
    aws_exec,
    aws_preflight,
)
from yoke_cli.commands.adapters.path_doctor import (
    path_check,
    path_fix,
    path_group,
    path_verify,
)
from yoke_cli.commands.adapters.source_dev_run import ruff_changed, source_dev_run
from yoke_cli.commands.adapters.runner_fleet import runner_fleet_exec
from yoke_cli.commands.adapters.pulumi import pulumi_exec
from yoke_cli.commands.adapters.vps import vps_start, vps_status, vps_stop
from yoke_cli.commands.git_hook import AdapterFn
from yoke_cli.commands.flag_adapters import (
    dev_db_admin_setup,
    dev_path_snapshot_prewarm,
    dev_setup,
    github_connect,
    github_disconnect,
    github_status,
    onboard,
    onboard_project,
    project_create,
    project_import,
)

TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("aws", "admin-link"): aws_admin_link,
    ("aws", "exec"): aws_exec,
    ("aws", "preflight"): aws_preflight,
    ("github", "connect"): github_connect,
    ("github", "disconnect"): github_disconnect,
    ("github", "status"): github_status,
    ("dev", "setup"): dev_setup,
    ("dev", "run"): source_dev_run,
    ("dev", "ruff-changed"): ruff_changed,
    ("dev", "db-admin", "setup"): dev_db_admin_setup,
    ("dev", "path-snapshot-prewarm"): dev_path_snapshot_prewarm,
    ("onboard",): onboard,
    ("onboard", "project"): onboard_project,
    ("path",): path_group,
    ("path", "check"): path_check,
    ("path", "fix"): path_fix,
    ("path", "verify"): path_verify,
    ("project", "create"): project_create,
    ("project", "import"): project_import,
    ("runner-fleet", "exec"): runner_fleet_exec,
    ("pulumi", "exec"): pulumi_exec,
    ("vps", "status"): vps_status,
    ("vps", "stop"): vps_stop,
    ("vps", "start"): vps_start,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke vps status": (
        "yoke vps status --stack STACK [--project PROJECT] [--region REGION]"
    ),
    "yoke vps stop": (
        "yoke vps stop --stack STACK [--project PROJECT] [--region REGION]"
    ),
    "yoke vps start": (
        "yoke vps start --stack STACK [--project PROJECT] [--region REGION]"
    ),
    "yoke aws admin-link": "yoke aws admin-link [--project PROJECT] [--region REGION]",
    "yoke aws exec": "yoke aws exec [--project PROJECT] [--region REGION] -- <aws-args>",
    "yoke aws preflight": "yoke aws preflight",
    "yoke github connect": "yoke github connect [--replace] [--add-installation] [--config PATH] [--json]",
    "yoke github disconnect": "yoke github disconnect [--config PATH] [--json]",
    "yoke github status": "yoke github status [--offline] [--json]",
    "yoke dev setup": "yoke dev setup [CHECKOUT]",
    "yoke dev run": "yoke dev run -- <command>",
    "yoke dev ruff-changed": ("yoke dev ruff-changed --base REF [--format-check]"),
    "yoke dev db-admin setup": (
        "yoke dev db-admin setup <env> [--control-plane-env CONNECTION_ENV] [--yes]"
    ),
    "yoke dev path-snapshot-prewarm": "yoke dev path-snapshot-prewarm",
    "yoke onboard": "yoke onboard [--project-mode machine-only|local-checkout] [--yes]",
    "yoke onboard project": "yoke onboard project CHECKOUT --slug SLUG --name NAME [--org ORG] [--yes|--dry-run]",
    "yoke path check": "yoke path check [--json]",
    "yoke path fix": "yoke path fix [--yes] [--file PATH] [--print-block] [--json]",
    "yoke path verify": "yoke path verify [--json]",
    "yoke project create": "yoke project create --slug SLUG --name NAME [--org ORG] --public-item-prefix PREFIX [--github-repo OWNER/REPO]",
    "yoke project import": "yoke project import --repo OWNER/REPO --slug SLUG [--checkout PATH]",
    "yoke runner-fleet exec": (
        "yoke runner-fleet exec --project PROJECT "
        "--settings-file STACK_CONFIG_JSON -- <command...>"
    ),
    "yoke pulumi exec": (
        "yoke pulumi exec --project NAME --stack STACK -- "
        "<init|preview|refresh|import|up|stack output args>"
    ),
}

__all__ = ["TOOL_SHAPED_SUBCOMMANDS", "TOOL_SHAPED_USAGE"]

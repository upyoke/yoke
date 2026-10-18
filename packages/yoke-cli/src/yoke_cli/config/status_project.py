"""Report checkout identity without turning invalid config into a traceback."""

from pathlib import Path
from typing import Any

from yoke_cli.config import machine_config
from yoke_contracts.machine_config.schema_connections import MachineConfigContractError
from yoke_contracts.machine_config.schema_projects import ValidationIssue


def _project_status(repo_root: Path, config_path: Path) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    board_scope = None
    try:
        project_id = machine_config.project_id(repo_root, config_path)
        board_scope = str(project_id) if project_id is not None else "all"
    except MachineConfigContractError as exc:
        project_id = None
        issues.append(
            ValidationIssue(
                "error",
                "project_mapping_invalid",
                str(exc),
                hint="Repair the reported machine-config issue, then rerun `yoke status`.",
            ).as_dict()
        )
    if project_id is None and not issues:
        issues.append(
            ValidationIssue(
                "warning",
                "project_mapping_missing",
                f"checkout {repo_root} is not mapped to a project_id",
                hint="Project-scoped commands need `yoke project register` first.",
            ).as_dict()
        )
    render = machine_config.board_render_path(repo_root, path=config_path)
    return {
        "repo_root": str(repo_root),
        "project_id": project_id,
        "board_settings_authority": "project-policy.settings.board",
        "board_render_path": str(render),
        "board_ts_path": f"{render}.ts",
        "board_art_path": str(machine_config.board_art_path(repo_root)),
        "board_scope": board_scope,
        "issues": issues,
    }

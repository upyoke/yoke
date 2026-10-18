"""Keep the laneless Task workflow out of code-repository projects.

Task pins worktrees=none and merge-free delivery, and a pinned item cannot
migrate across workflows. Source work filed as Task in a project with a
registered code repository therefore strands its worker without a lane, so
creation refuses it and names Dash, the lane-owning direct workflow.
Projects without a repository keep Task for folder-only and non-code work.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.project_identity import placeholder

TASK_WORKFLOW_ID = "task"
TASK_IN_CODE_PROJECT_ERROR_CODE = "task_workflow_code_project"


def project_code_repository(conn: Any, project_id: int) -> str:
    """Return the project's registered code repository, or ``""`` for none."""
    row = conn.execute(
        "SELECT COALESCE(github_repo, '') FROM projects "
        f"WHERE id = {placeholder(conn)}",
        (project_id,),
    ).fetchone()
    return str(row[0]).strip() if row and row[0] else ""


def task_in_code_project_refusal(
    conn: Any, *, workflow_id: str, project_id: int, project_slug: str
) -> Optional[dict]:
    """Return the create refusal for Task in a code project, else ``None``."""
    if workflow_id != TASK_WORKFLOW_ID:
        return None
    repository = project_code_repository(conn, project_id)
    if not repository:
        return None
    return {
        "success": False,
        "error_code": TASK_IN_CODE_PROJECT_ERROR_CODE,
        "error": (
            f"Task refused: project {project_slug} has the code repository "
            f"{repository}, and Task items get no git lane or merge. File "
            "code project work with yoke dash TITLE SPEC "
            f"--project {project_slug} --execution-instructions-considered "
            '(or /yoke dash "spec" to file and execute). Task stays '
            "available for projects without a code repository."
        ),
    }

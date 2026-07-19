"""Resolve the project-owned source used by core-container delivery."""

from pathlib import Path

from yoke_core.domain import db_helpers
from yoke_core.domain.deploy_core_container_image import CoreDeployError
from yoke_core.domain.project_checkout_locations import checkout_for_project


def project_source_root(project: str, repo_path: str | Path = "") -> Path:
    """Return an explicit or registered project checkout, failing closed."""

    if repo_path:
        root = Path(repo_path).expanduser().resolve()
    else:
        conn = db_helpers.connect()
        try:
            checkout = checkout_for_project(conn, project)
        finally:
            conn.close()
        if checkout is None:
            raise CoreDeployError(
                f"[core-deploy] project {project!r} has no machine-local checkout; "
                "pass its repository path"
            )
        root = checkout.expanduser().resolve()
    if not root.is_dir():
        raise CoreDeployError(f"[core-deploy] project checkout is missing: {root}")
    return root


__all__ = ["project_source_root"]

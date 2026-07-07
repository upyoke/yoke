"""Canonical project GitHub auth + repo resolver.

Yoke-owned GitHub callers resolve repo + token through
``resolve_project_github_auth`` and fail closed with typed
``ProjectGithubAuthError`` subclasses. Repo metadata lives on
``projects.github_repo``; token material lives in ``capability_secrets``
and resolves through ``cmd_capability_get_secret``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.projects_capabilities import cmd_capability_get_secret

def _missing_table_errors(conn) -> tuple:
    return db_backend.operational_error_types(conn)


def _p(conn) -> str: return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rollback_quietly(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


class ProjectGithubAuthError(Exception):
    """Base class for canonical project GitHub auth failures."""

    code: str = "project_github_auth_error"

    def __init__(self, project: str, message: str) -> None:
        super().__init__(message)
        self.project = project


class MissingCapability(ProjectGithubAuthError):
    """No ``project_capabilities`` row for ``(project, type='github')``."""

    code = "missing_capability"


class MissingRepoMetadata(ProjectGithubAuthError):
    """``projects.github_repo`` is unset or empty for the project."""

    code = "missing_repo_metadata"


class MissingToken(ProjectGithubAuthError):
    """No ``capability_secrets`` row, or literal token resolves empty."""

    code = "missing_token"


class InvalidSecretSource(ProjectGithubAuthError):
    """``capability_secrets.source`` is not the supported literal shape."""

    code = "invalid_secret_source"


class InvalidToken(ProjectGithubAuthError):
    """Token resolved but ``gh`` rejected it as unauthorized.

    Exported for downstream callers observing a ``gh`` 401/403; v0 resolver
    itself does not call ``gh``.
    """

    code = "invalid_token"


class TransportFailure(ProjectGithubAuthError):
    """``gh`` could not reach GitHub (network/timeout).

    Exported for downstream callers; v0 resolver does not call ``gh``.
    """

    code = "transport_failure"


@dataclass(frozen=True)
class ProjectGithubAuth:
    """Resolved project GitHub auth bundle.

    Frozen so callers cannot mutate the returned env dict by accident.
    ``env`` is a fresh copy of the caller's ``base_env`` (or
    ``os.environ``) with ``GH_TOKEN`` set; pass directly to
    ``subprocess.run(..., env=...)``.
    """

    project: str
    repo: str
    token: str
    env: Mapping[str, str] = field()


def _read_github_state(
    project: str,
    db_path: Optional[str],
    conn: Optional[Any] = None,
) -> tuple[str, bool, str, Optional[str]]:
    """Return project slug, capability presence, repo, and token source."""
    own_conn = conn is None
    if own_conn:
        conn = connect(db_path)
    try:
        try:
            ident = resolve_project(conn, project, required=True)
        except LookupError:
            return str(project), False, "", None
        except _missing_table_errors(conn):
            _rollback_quietly(conn)
            return str(project), False, "", None
        assert ident is not None
        project_id = ident.id
        project_slug = ident.slug
        try:
            marker = _p(conn)
            cap_row = conn.execute(
                "SELECT 1 FROM project_capabilities "
                f"WHERE project_id={marker} AND type='github' LIMIT 1",
                (project_id,),
            ).fetchone()
            has_capability = cap_row is not None
        except _missing_table_errors(conn):
            _rollback_quietly(conn)
            has_capability = False

        try:
            repo_row = conn.execute(
                "SELECT COALESCE(github_repo, '') AS repo FROM projects "
                f"WHERE id={_p(conn)}",
                (project_id,),
            ).fetchone()
            repo = str(repo_row["repo"] or "") if repo_row is not None else ""
        except _missing_table_errors(conn):
            _rollback_quietly(conn)
            repo = ""

        try:
            secret_row = conn.execute(
                "SELECT source, value FROM capability_secrets "
                f"WHERE project_id={_p(conn)} AND type='github' AND key='token' LIMIT 1",
                (project_id,),
            ).fetchone()
        except _missing_table_errors(conn):
            _rollback_quietly(conn)
            secret_row = None
        if secret_row is None:
            source: Optional[str] = None
        else:
            source = str(secret_row["source"])
    finally:
        if own_conn:
            conn.close()
    return project_slug, has_capability, repo, source


def resolve_project_github_auth(
    project: str,
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
    base_env: Optional[Mapping[str, str]] = None,
) -> ProjectGithubAuth:
    """Resolve canonical GitHub repo + token for ``project``.

    Failure modes (typed):

    - :class:`MissingCapability` — no ``project_capabilities`` row.
    - :class:`MissingRepoMetadata` — ``projects.github_repo`` empty.
    - :class:`MissingToken` — no ``capability_secrets`` row, or literal token
      resolves empty.
    - :class:`InvalidSecretSource` — ``capability_secrets.source`` is not
      ``literal``.

    Pass ``conn`` to resolve against a caller-owned connection (test fixture
    DBs, in-memory schemas) so the resolver does not silently fall back to
    canonical ``YOKE_DB`` and read state the caller never set up. When
    ``conn`` is omitted the resolver opens a connection via ``db_path`` (or
    the canonical resolver) as before — existing callers stay backward
    compatible.

    Capture ``os.environ`` inside the function (not at module top) so test
    ``monkeypatch.setenv`` flows through.
    """

    project_slug, has_capability, repo, source = _read_github_state(
        project, db_path, conn=conn,
    )

    # Capability row gates first so operators see the most actionable
    # diagnostic when nothing is configured yet.
    if not has_capability:
        raise MissingCapability(
            project_slug,
            f"project '{project_slug}' has no 'github' capability row; "
            f"configure it via `python3 -m yoke_core.domain.projects "
            f"capability-add {project_slug} github`",
        )

    repo_clean = repo.strip()
    if not repo_clean:
        raise MissingRepoMetadata(
            project_slug,
            f"project '{project_slug}' has no github_repo configured",
        )

    if source is None:
        raise MissingToken(
            project_slug,
            f"project '{project_slug}' has no github token in capability_secrets",
        )
    if source != "literal":
        raise InvalidSecretSource(
            project_slug,
            f"project '{project_slug}' github token uses unsupported "
            f"capability_secrets.source={source!r}; re-import it via "
            "`yoke projects capability secret set --project "
            f"{project_slug} --cap-type github --key token <token>`",
        )

    try:
        raw = cmd_capability_get_secret(
            project_slug, "github", "token", db_path=db_path, conn=conn,
        )
    except ValueError as exc:
        raise InvalidSecretSource(project_slug, str(exc)) from exc
    except db_backend.database_error_types(conn) as exc:  # defensive
        raise MissingToken(
            project_slug,
            f"project '{project_slug}' github token lookup failed: {exc}",
        ) from exc

    token = (raw or "").strip() if isinstance(raw, str) else ""

    if not token:
        raise MissingToken(
            project_slug,
            f"project '{project_slug}' github token resolved empty "
            f"(source='{source}')",
        )

    # Clone base_env (or os.environ snapshot at call time) so the caller's
    # mapping is never mutated.
    env: dict[str, str] = dict(os.environ) if base_env is None else dict(base_env)
    env["GH_TOKEN"] = token

    return ProjectGithubAuth(
        project=project_slug, repo=repo_clean, token=token, env=env,
    )


_HINT_BY_CODE: Mapping[str, str] = {
    "missing_capability": (
        "python3 -m yoke_core.domain.projects capability-add "
        "{project} github"
    ),
    "missing_repo_metadata": (
        "python3 -m yoke_core.domain.projects set "
        "{project} github_repo <owner>/<repo>"
    ),
    "missing_token": (
        "yoke projects capability secret set --project {project} "
        "--cap-type github --key token <token>"
    ),
    "invalid_secret_source": (
        "import a fresh value via `yoke projects capability secret set "
        "--project {project} --cap-type github --key token <token>`"
    ),
    "invalid_token": (
        "rotate via `yoke projects capability secret set "
        "--project {project} --cap-type github --key token <new-token>`"
    ),
    "transport_failure": (
        "retry once network is restored; the resolver is idempotent"
    ),
}


def repair_command_hint(
    error: ProjectGithubAuthError,
    project: str,
) -> str:
    """Concrete operator-facing repair hint for ``error``.
    Keyed off the class-level ``code`` attribute so a new subclass needs
    one extra entry in :data:`_HINT_BY_CODE` (and nothing else).
    """
    template = _HINT_BY_CODE.get(error.code)
    if template is None:
        return (
            f"unknown project_github_auth error code '{error.code}'; "
            "check `python3 -m yoke_core.domain.projects` "
            "capability/secret commands"
        )
    return template.format(project=project)

"""Project identity helpers for engine tests."""

from __future__ import annotations


_PROJECT_IDS = {"yoke": 1, "externalwebapp": 2, "orphan": 3, "a": 4, "b": 5}


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_id(slug: str | None) -> int | None:
    if slug is None:
        return None
    return _PROJECT_IDS.get(slug, 999)


def _seed_project(
    conn,
    slug: str,
    name: str | None = None,
    github_repo: str | None = None,
    public_item_prefix: str | None = None,
) -> None:
    p = _p(conn)
    project_id = _project_id(slug)
    prefix = public_item_prefix or {"yoke": "YOK", "externalwebapp": "EXT"}.get(
        slug, slug.upper()
    )
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, default_branch, created_at, "
        "github_repo, public_item_prefix) "
        f"VALUES ({p}, {p}, {p}, 'main', '2026-01-01T00:00:00Z', {p}, {p}) "
        "ON CONFLICT(id) DO UPDATE SET "
        "slug=excluded.slug, name=excluded.name, "
        "github_repo=excluded.github_repo, "
        "public_item_prefix=excluded.public_item_prefix",
        (
            project_id,
            slug,
            name or slug.title(),
            github_repo,
            prefix,
        ),
    )


def _insert_item(
    conn,
    item_id: int,
    title: str = "Test",
    project: str | None = "yoke",
    **fields,
) -> None:
    p = _p(conn)
    data = {
        "id": item_id,
        "title": title,
        "project_id": _project_id(project),
        "project_sequence": item_id,
        **fields,
    }
    columns = list(data)
    placeholders = ", ".join(p for _ in columns)
    conn.execute(
        f"INSERT INTO items ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(data[col] for col in columns),
    )


def _insert_deployment_flow(
    conn,
    flow_id: str,
    project: str = "yoke",
    stages: str = "[]",
    **fields,
) -> None:
    p = _p(conn)
    data = {
        "id": flow_id,
        "project_id": _project_id(project),
        "stages": stages,
        **fields,
    }
    columns = list(data)
    placeholders = ", ".join(p for _ in columns)
    conn.execute(
        f"INSERT INTO deployment_flows ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(data[col] for col in columns),
    )

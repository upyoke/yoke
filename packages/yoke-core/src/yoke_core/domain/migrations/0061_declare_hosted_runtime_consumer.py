"""Declare the hosted-runtime QA consumer on the environments that share it.

The QA bridge that lets one project run cases against another project's
hosted-runtime environment used to be fixed in code: the ``platform``
project's ``Yoke API`` environments served the ``yoke`` project in the same
organization. The bridge now reads ``qa.hosted_runtime_consumer`` from the
environment instead, so this entry writes that former rule into the stored
documents it governed. It only adds the key where it is absent, so an
operator's own declaration is never overwritten and re-applying is a no-op.
It declares no invariant: an operator may later withdraw the share by
removing the key, and no stored fact here is permanent.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.qa_hosted_runtime_identity import (
    CANONICAL_RUNTIME_SITE_NAME,
    QA_HOSTED_RUNTIME_CONSUMER_PATH,
)
from yoke_core.domain.schema_common import _table_exists

#: The former in-code bridge: host project slug -> consumer project slug.
_FORMER_HOST_PROJECT = "platform"
_FORMER_CONSUMER_PROJECT = "yoke"


def _rows(conn: Any) -> list[Any]:
    if not all(
        _table_exists(conn, table) for table in ("environments", "sites", "projects")
    ):
        return []
    marker = "%s" if connection_is_postgres(conn) else "?"
    return conn.execute(
        "SELECT e.id, e.settings FROM environments e "
        "JOIN sites s ON s.id = e.site "
        "JOIN projects host ON host.id = s.project_id "
        "JOIN projects consumer ON consumer.org_id = host.org_id "
        f"WHERE s.name = {marker} AND host.slug = {marker} "
        f"AND consumer.slug = {marker} ORDER BY e.id",
        (CANONICAL_RUNTIME_SITE_NAME, _FORMER_HOST_PROJECT, _FORMER_CONSUMER_PROJECT),
    ).fetchall()


def _settings(row: Any) -> dict[str, Any]:
    try:
        settings = json_helper.loads_text(str(row[1] or "{}"))
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        return settings
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"environment_settings_invalid: environment {row[0]} cannot "
            "converge its hosted-runtime consumer. Recovery: repair its "
            "settings to a JSON object through yoke projects "
            "environment-settings merge, then retry rehearsal or boot."
        ) from exc


def _needs_consumer(settings: dict[str, Any]) -> bool:
    qa = settings.get("qa")
    if not isinstance(qa, dict) or qa.get("hosted_runtime") is not True:
        return False
    key = QA_HOSTED_RUNTIME_CONSUMER_PATH.split(".", 1)[1]
    return not str(qa.get(key) or "").strip()


def apply(conn: Any) -> None:
    marker = "%s" if connection_is_postgres(conn) else "?"
    key = QA_HOSTED_RUNTIME_CONSUMER_PATH.split(".", 1)[1]
    for row in _rows(conn):
        settings = _settings(row)
        if not _needs_consumer(settings):
            continue
        settings["qa"][key] = _FORMER_CONSUMER_PROJECT
        conn.execute(
            f"UPDATE environments SET settings = {marker} WHERE id = {marker}",
            (json_helper.dumps_compact(settings), int(row[0])),
        )

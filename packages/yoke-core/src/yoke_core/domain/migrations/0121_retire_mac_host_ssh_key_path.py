"""Remove ``servers[*].mac_host_ssh_key_path`` from environment settings.

Box db-admin setup now derives a per-machine Mac-host key under
``~/.yoke/secrets``, so nothing reads the stored path. Replay is a no-op.
"""

from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres

_RETIRED_KEY = "mac_host_ssh_key_path"


def apply(conn):
    """Strip the retired key from every environment's servers."""
    p = "%s" if connection_is_postgres(conn) else "?"
    for row_id, raw in conn.execute("SELECT id, settings FROM environments").fetchall():
        try:
            document = json_helper.loads_text(str(raw or "{}"))
        except ValueError:
            continue
        if not isinstance(document, dict) or not _strip(document):
            continue
        conn.execute(
            f"UPDATE environments SET settings={p} WHERE id={p}",
            (json_helper.dumps_compact(document), row_id),
        )


def _strip(document):
    servers = document.get("servers")
    if not isinstance(servers, list):
        return False
    held = [s for s in servers if isinstance(s, dict) and _RETIRED_KEY in s]
    for server in held:
        del server[_RETIRED_KEY]
    return bool(held)

"""Remove retired renderer fields from every project's capability settings.

0108 cleaned live projects only, but the shipped capability settings
contract covers every ``project_capabilities`` row, retired projects
included (buzz kept ``stack_state`` and ``stacks`` on its pulumi-state
row). This pass strips the same fields from every row and removes every
``aws-route53`` capability row, whatever the project's state. Retired
projects' site and environment settings stay untouched. Replay is a no-op.
"""

from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres

_CAPABILITY_KEYS = {
    "pulumi-state": (
        "infra_stack_name", "migration_receipts", "stack_state", "stacks",
        "vps_stack_name",
    ),
    "container-registry": ("manage_platform_image_lifecycle",),
    "github": ("ci_oidc_manage_provider",),
}


def apply(conn):
    """Strip retired renderer fields from all capability rows."""
    p = "%s" if connection_is_postgres(conn) else "?"
    for cap_type, keys in _CAPABILITY_KEYS.items():
        rows = conn.execute(
            f"SELECT id, settings FROM project_capabilities WHERE type={p}",
            (cap_type,),
        ).fetchall()
        for row_id, raw in rows:
            try:
                document = json_helper.loads_text(str(raw or "{}"))
            except ValueError:
                continue
            if not isinstance(document, dict):
                continue
            present = [key for key in keys if key in document]
            if not present:
                continue
            for key in present:
                del document[key]
            conn.execute(
                f"UPDATE project_capabilities SET settings={p} WHERE id={p}",
                (json_helper.dumps_compact(document), row_id),
            )
    conn.execute(
        f"DELETE FROM project_capabilities WHERE type={p}", ("aws-route53",)
    )

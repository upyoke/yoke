"""Remove the settings only Yoke's retired Pulumi stack renderer read.

Pulumi stacks now run from each project's checked-in
``infra/Pulumi.<stack>.yaml``, which holds the project's own values and its
``secretsprovider``/``encryptedkey`` lines. The values below were stored only
so the renderer could forward them into templates; nothing reads them now.
Retired projects are left untouched. Replay is a no-op.
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
_RETIRED_CAPABILITY_TYPES = ("aws-route53",)
_DOMAIN_KEYS = (
    "certificate_arn", "hosted_zone_id", "manage_registration", "mx_records",
    "txt_records",
)
_CDN_KEYS = ("distribution_bucket_name", "distribution_domain", "origin_id")
_SITE_PULUMI_KEYS = ("stack_state", "stacks")
_DATABASE_KEYS = (
    "allowed_security_group_ids", "backup_retention_days", "engine_version",
    "master_username", "max_capacity_acu", "min_capacity_acu",
    "seconds_until_auto_pause",
)
_SERVER_KEYS = (
    "aws_key_pair_name", "description", "iam_instance_profile_name",
    "instance_type", "root_volume_gb",
)
_TEMPLATE_CONFIG = {
    "container-registry": (
        '[{"key":"repository","description":"Registry repository name '
        '(e.g. <project>-core)","secret":false}]'
    ),
    "github": (
        '[{"key":"repo_owner","description":"GitHub repo owner","secret":false},'
        '{"key":"repo_name","description":"GitHub repo name","secret":false},'
        '{"key":"installation_id","description":"GitHub App installation id",'
        '"secret":false},'
        '{"key":"repository_id","description":"GitHub repository id",'
        '"secret":false}]'
    ),
}


def apply(conn):
    """Strip renderer-only keys from live projects' stored settings."""
    p = "%s" if connection_is_postgres(conn) else "?"
    live = "SELECT id FROM projects WHERE retired_at IS NULL"
    for cap_type, keys in _CAPABILITY_KEYS.items():
        rows = conn.execute(
            f"SELECT id, settings FROM project_capabilities WHERE type={p} "
            f"AND project_id IN ({live})",
            (cap_type,),
        ).fetchall()
        for row_id, raw in rows:
            _rewrite(conn, "project_capabilities", row_id, raw, p,
                     lambda doc, keys=keys: _drop(doc, keys))
    for cap_type in _RETIRED_CAPABILITY_TYPES:
        conn.execute(
            f"DELETE FROM project_capabilities WHERE type={p} "
            f"AND project_id IN ({live})",
            (cap_type,),
        )
        conn.execute(f"DELETE FROM capability_templates WHERE id={p}", (cap_type,))
    for template_id, config in _TEMPLATE_CONFIG.items():
        conn.execute(
            f"UPDATE capability_templates SET required_config={p} WHERE id={p}",
            (config, template_id),
        )
    for row_id, raw in conn.execute(
        f"SELECT id, settings FROM sites WHERE project_id IN ({live})"
    ).fetchall():
        _rewrite(conn, "sites", row_id, raw, p, _clean_site)
    for row_id, raw in conn.execute(
        f"SELECT id, settings FROM environments WHERE project_id IN ({live})"
    ).fetchall():
        _rewrite(conn, "environments", row_id, raw, p, _clean_environment)


def _rewrite(conn, table, row_id, raw, p, clean):
    try:
        document = json_helper.loads_text(str(raw or "{}"))
    except ValueError:
        return
    if not isinstance(document, dict) or not clean(document):
        return
    conn.execute(
        f"UPDATE {table} SET settings={p} WHERE id={p}",
        (json_helper.dumps_compact(document), row_id),
    )


def _drop(document, keys):
    changed = False
    for key in keys:
        if isinstance(document, dict) and key in document:
            del document[key]
            changed = True
    return changed


def _drop_nested(document, parent, keys):
    child = document.get(parent)
    changed = False
    if isinstance(child, dict):
        changed = _drop(child, keys)
        if not child:
            del document[parent]
            changed = True
    return changed


def _drop_each(document, parent, keys):
    entries = document.get(parent)
    if not isinstance(entries, list):
        return False
    return any([_drop(entry, keys) for entry in entries if isinstance(entry, dict)])


def _clean_site(document):
    return any([
        _drop_nested(document, "cdn", _CDN_KEYS),
        _drop_nested(document, "pulumi", _SITE_PULUMI_KEYS),
        _drop_each(document, "domains", _DOMAIN_KEYS),
    ])


def _clean_environment(document):
    return any([
        _drop_nested(document, "database", _DATABASE_KEYS),
        _drop_nested(document, "distribution", ("repository_variable_namespace",)),
        _drop_nested(document, "pulumi", ("encrypted_key", "secrets_provider")),
        _drop_each(document, "servers", _SERVER_KEYS),
    ])

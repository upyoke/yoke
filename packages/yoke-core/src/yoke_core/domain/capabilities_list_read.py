"""Read-only project-capability roster with verification provenance.

The read behind ``projects.capabilities.list``: one row per
``project_capabilities`` declaration carrying the stored ``type``
vocabulary, a derived kind/state pair, a curated non-secret settings
summary, and verification freshness. The ``capability_secrets`` table
holds literal secret values — this read never selects from it, not even
a join.

``project_capabilities.verified_at`` has no timestamp writer today, so
most rows carry NULL; the derived ``state`` renders that honestly as
``configured_unverified`` rather than pretending a verification
happened. GitHub verification freshness genuinely lives on
``github_app_installations.last_verified_at`` and
``project_github_repo_bindings.last_verified_at``, so rows of the
stored ``github`` type overlay the newest of those stamps as the row's
``verified_at`` surrogate, with ``verified_source`` naming where the
stamp came from.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_contracts.github_app_tokens import GITHUB_CAPABILITY_TYPE

from yoke_core.domain import db_helpers, json_helper
from yoke_core.domain.migration_model_capability_validation import (
    CAPABILITY_TYPE as MIGRATION_MODEL_CAPABILITY_TYPE,
)
from yoke_core.domain.project_identity import resolve_project_id


KIND_DECLARED_MODEL = "declared_model"
KIND_PROVIDER_ACCESS = "provider_access"

#: Capability types that declare a model of the project's world rather
#: than granting access to an external provider. The architecture model
#: a project may declare is NOT in this set because it does not live in
#: ``project_capabilities`` at all — it is a Project Structure family
#: (``project_structure`` rows), so this read never sees it.
DECLARED_MODEL_TYPES = frozenset({MIGRATION_MODEL_CAPABILITY_TYPE})

STATE_DECLARED = "declared"
STATE_VERIFIED = "verified"
STATE_CONFIGURED_UNVERIFIED = "configured_unverified"

VERIFIED_SOURCE_CAPABILITY = "capability"
VERIFIED_SOURCE_REPO_BINDING = "repo-binding"

#: Row keys every ``projects.capabilities.list`` row carries, in
#: presentation order. Every field is a scalar.
CAPABILITY_LIST_FIELDS = (
    "type",
    "kind",
    "state",
    "project_id",
    "project",
    "settings_summary",
    "verified_at",
    "verified_source",
    "created_at",
)

#: Known-non-secret scalar settings keys, tried in declaration order for
#: any stored type without a bespoke summarizer below. Values still pass
#: the display-safety check before rendering; types with none of these
#: keys summarize as empty rather than guessing.
GENERIC_SUMMARY_KEYS = ("region", "host", "domain", "repository")


def _display_safe(value: Any) -> Optional[str]:
    """The value as display text, or ``None`` when it must not render.

    Conservative by design: anything shaped like a filesystem path or
    like key material is suppressed, and non-scalar values never render.
    When in doubt, omit.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(("/", "~", ".")) or "/" in text or "\\" in text:
        return None  # filesystem-path shaped
    if len(text) > 40 or any(ch.isspace() for ch in text):
        return None  # key-material or free-text shaped
    return text


def _repo_slug_safe(value: Any) -> Optional[str]:
    """An ``owner/name`` repo slug, or ``None`` — the one sanctioned slash."""
    if not isinstance(value, str):
        return None
    owner, separator, name = value.strip().partition("/")
    if not separator:
        return None
    safe_owner = _display_safe(owner)
    safe_name = _display_safe(name)
    if safe_owner and safe_name:
        return f"{safe_owner}/{safe_name}"
    return None


def _github_summary(settings: Dict[str, Any]) -> str:
    owner = _display_safe(settings.get("repo_owner"))
    name = _display_safe(settings.get("repo_name"))
    if owner and name:
        return f"{owner}/{name}"
    return ""


def _migration_model_summary(settings: Dict[str, Any]) -> str:
    """Model slugs with each declared runner kind, e.g. ``primary (module)``."""
    models = settings.get("models")
    if not isinstance(models, dict):
        return ""
    parts: List[str] = []
    for slug in sorted(models):
        label = _display_safe(slug)
        if label is None:
            continue
        declared = models.get(slug)
        runner = declared.get("runner") if isinstance(declared, dict) else None
        runner_kind = _display_safe(
            runner.get("kind") if isinstance(runner, dict) else None,
        )
        parts.append(f"{label} ({runner_kind})" if runner_kind else label)
    return ", ".join(parts)


def summarize_settings(cap_type: str, settings_json: Any) -> str:
    """A one-line curated non-secret summary of a settings document."""
    try:
        parsed = json_helper.loads_text(str(settings_json or "{}"))
    except Exception:
        return ""
    if not isinstance(parsed, dict):
        return ""
    if cap_type == GITHUB_CAPABILITY_TYPE:
        return _github_summary(parsed)
    if cap_type == MIGRATION_MODEL_CAPABILITY_TYPE:
        return _migration_model_summary(parsed)
    parts: List[str] = []
    repo_slug = _repo_slug_safe(parsed.get("repo"))
    if repo_slug:
        parts.append(repo_slug)
    for key in GENERIC_SUMMARY_KEYS:
        text = _display_safe(parsed.get(key))
        if text is not None:
            parts.append(f"{key}={text}")
    return " · ".join(parts)


def _github_freshness_by_project(conn: Any) -> Dict[int, str]:
    """Newest GitHub verification stamp per project.

    The stamps live on the App installation and the repo binding, not on
    the capability row. Timestamps are uniform ISO-8601 text, so the
    lexicographic MAX/GREATEST matches chronological order.
    """
    rows = conn.execute(
        "SELECT b.project_id, "
        "NULLIF(MAX(GREATEST(COALESCE(b.last_verified_at, ''), "
        "COALESCE(i.last_verified_at, ''))), '') AS last_verified_at "
        "FROM project_github_repo_bindings b "
        "LEFT JOIN github_app_installations i "
        "ON i.installation_id = b.installation_id "
        "GROUP BY b.project_id",
    ).fetchall()
    freshness: Dict[int, str] = {}
    for raw in rows:
        row = dict(raw)
        if row.get("last_verified_at"):
            freshness[int(row["project_id"])] = str(row["last_verified_at"])
    return freshness


def list_capabilities(
    *,
    project: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List declared project capabilities, one row per declaration.

    ``project`` filters to one project (slug or id, resolved
    server-side); ``None`` serves the whole universe. Rows order by
    project slug then capability type so the roster reads stably.
    """
    conn = db_helpers.connect()
    try:
        where = ""
        params: List[Any] = []
        if project:
            where = "WHERE c.project_id = %s"
            params.append(resolve_project_id(conn, project))
        rows = conn.execute(
            "SELECT c.project_id, pr.slug AS project, c.type, c.settings, "
            "c.verified_at, c.created_at "
            "FROM project_capabilities c "
            "LEFT JOIN projects pr ON pr.id = c.project_id "
            f"{where} "
            "ORDER BY pr.slug ASC, c.type ASC",
            tuple(params),
        ).fetchall()

        github_freshness: Dict[int, str] = {}
        if any(
            str(dict(raw)["type"]) == GITHUB_CAPABILITY_TYPE for raw in rows
        ):
            github_freshness = _github_freshness_by_project(conn)

        result: List[Dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            cap_type = str(row["type"])
            kind = (
                KIND_DECLARED_MODEL
                if cap_type in DECLARED_MODEL_TYPES
                else KIND_PROVIDER_ACCESS
            )
            verified_at = row.get("verified_at") or None
            verified_source = (
                VERIFIED_SOURCE_CAPABILITY if verified_at else None
            )
            if cap_type == GITHUB_CAPABILITY_TYPE:
                overlay = github_freshness.get(int(row["project_id"]))
                if overlay and (
                    verified_at is None or overlay > str(verified_at)
                ):
                    verified_at = overlay
                    verified_source = VERIFIED_SOURCE_REPO_BINDING
            if kind == KIND_DECLARED_MODEL:
                state = STATE_DECLARED
            elif verified_at:
                state = STATE_VERIFIED
            else:
                state = STATE_CONFIGURED_UNVERIFIED
            result.append({
                "type": cap_type,
                "kind": kind,
                "state": state,
                "project_id": row.get("project_id"),
                "project": row.get("project"),
                "settings_summary": summarize_settings(
                    cap_type, row.get("settings"),
                ),
                "verified_at": verified_at,
                "verified_source": verified_source,
                "created_at": row.get("created_at"),
            })
        return result
    finally:
        conn.close()


__all__ = [
    "CAPABILITY_LIST_FIELDS",
    "DECLARED_MODEL_TYPES",
    "GENERIC_SUMMARY_KEYS",
    "KIND_DECLARED_MODEL",
    "KIND_PROVIDER_ACCESS",
    "STATE_CONFIGURED_UNVERIFIED",
    "STATE_DECLARED",
    "STATE_VERIFIED",
    "VERIFIED_SOURCE_CAPABILITY",
    "VERIFIED_SOURCE_REPO_BINDING",
    "list_capabilities",
    "summarize_settings",
]

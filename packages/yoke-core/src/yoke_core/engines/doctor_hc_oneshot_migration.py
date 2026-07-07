"""HC-oneshot-migration-coverage: governed DB-mutation authoring drift.

Defense-in-depth check; upstream shepherd/refine gates enforce the
contract at authoring time. The governed contract is in AGENTS.md
``## Governed DB Mutation``. This HC scans for drift classes the
gates can miss:

(a) items with malformed ``db_mutation_profile`` (missing
    ``model_name`` / ``mutation_intent`` / ``migration_modules``;
    apply intents also need ``compatibility_class`` and
    ``affected_surfaces``);
(b) items declaring ``compatibility_class='pre_merge_safe'`` whose
    ``db_compatibility_attestation`` is absent or missing any of
    ``pre_merge_readers_writers`` / ``invariants`` /
    ``rehearsal_commands`` / ``residual_risk_notes``;
(c) live ``record_audit_fingerprint(`` call sites without a paired
    decision record at ``docs/archive/decisions/<name>.md``;
(d) ``migration_audit`` rows with a non-canonical ``backup_path``
    (the shared backup substrate emits
    ``backups/{stem}.{YYYYMMDD-HHMMSS}.<reason>.sqlite3``). Rows
    whose ``exception_reason`` names an existing decision record are
    treated as documented dispositions and skipped.

Terminal items (``done`` / ``cancelled`` / ``failed`` / ``stopped``)
are skipped. Emits WARN with concrete drift details.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-oneshot-migration-coverage"
_HC_DESC = "Governed DB-mutation authoring coverage"

_TERMINAL_STATUSES = (
    "done",
    "cancelled",
    "failed",
    "stopped",
)

_REQUIRED_PROFILE_FIELDS = (
    "model_name",
    "mutation_intent",
    "migration_modules",
)

# Fields that the `apply` flow additionally requires.  `retire` intent
# does not require a compatibility class because it routes through the
# decision-record pathway rather than the live-apply contract.
_REQUIRED_APPLY_FIELDS = (
    "compatibility_class",
    "affected_surfaces",
)

_REQUIRED_ATTESTATION_FIELDS = (
    "pre_merge_readers_writers",
    "invariants",
    "rehearsal_commands",
    "residual_risk_notes",
)


def _parse_json_field(raw: Optional[str]) -> Optional[Dict]:
    """Return a dict payload for a structured JSON field, or None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == "null":
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _profile_issues(item_id: int, profile: Dict) -> List[str]:
    """Return per-item drift messages for a governed profile."""
    state = str(profile.get("state") or "").strip()
    if not state or state == "none":
        return []

    issues: List[str] = []
    missing: List[str] = []
    for field in _REQUIRED_PROFILE_FIELDS:
        value = profile.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)

    intent = str(profile.get("mutation_intent") or "").strip()
    if intent == "apply":
        for field in _REQUIRED_APPLY_FIELDS:
            value = profile.get(field)
            if value is None or value == "" or value == []:
                missing.append(field)

    if missing:
        issues.append(
            f"- YOK-{item_id}: db_mutation_profile missing required "
            f"field(s): {', '.join(sorted(set(missing)))}."
        )

    modules = profile.get("migration_modules")
    if modules is not None and not isinstance(modules, list):
        issues.append(
            f"- YOK-{item_id}: db_mutation_profile.migration_modules "
            f"must be a list (got {type(modules).__name__})."
        )

    if intent and intent not in ("apply", "retire"):
        issues.append(
            f"- YOK-{item_id}: db_mutation_profile.mutation_intent must "
            f"be 'apply' or 'retire' (got {intent!r})."
        )

    return issues


def _attestation_issues(
    item_id: int, profile: Dict, attestation_raw: Optional[str]
) -> List[str]:
    """Return per-item drift messages for pre_merge_safe attestation."""
    compat = str(profile.get("compatibility_class") or "").strip()
    if compat != "pre_merge_safe":
        return []

    attestation = _parse_json_field(attestation_raw)
    if attestation is None:
        return [
            f"- YOK-{item_id}: pre_merge_safe profile with no "
            f"db_compatibility_attestation — all four authored fields "
            f"must be present and non-empty."
        ]

    missing: List[str] = []
    for field in _REQUIRED_ATTESTATION_FIELDS:
        value = attestation.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)

    if missing:
        return [
            f"- YOK-{item_id}: pre_merge_safe attestation missing or "
            f"empty field(s): {', '.join(sorted(set(missing)))}."
        ]
    return []


_CALL_SITE_RE = re.compile(
    r"record_audit_fingerprint\s*\(",
)
_NAME_KW_RE = re.compile(
    r'name\s*=\s*["\']([^"\']+)["\']',
)

# Canonical backup filename shapes for migration audit rows:
#
#     .yoke/backups/postgres.{YYYYMMDD-HHMMSS}.<reason>.sql
#     backups/{db_stem}.{YYYYMMDD-HHMMSS}.<reason>.sqlite3
#
# Active Yoke authority creates Postgres dumps under project-local .yoke.
# The HC still recognizes the old SQLite shape so historical populated
# ``backup_path`` rows can be distinguished from pre-fix drift.
_CANONICAL_BACKUP_RE = re.compile(
    r"(^|/)backups/(?:postgres\.\d{8}-\d{6}\.[^/]+\.sql|"
    r"[^/]+\.\d{8}-\d{6}\.[^/]+\.sqlite3)$"
)


def _scan_call_sites(api_root: Path) -> List[Dict[str, str]]:
    """Return a list of ``{path, name}`` dicts for each live call site."""
    out: List[Dict[str, str]] = []
    if not api_root.is_dir():
        return out
    for py in sorted(api_root.rglob("*.py")):
        rel = py.name
        # Skip tests — they exercise the helper but do not carry a
        # governance obligation to pair a decision record.
        if rel.startswith("test_") or rel.endswith("_test.py"):
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Cheap substring probe first so we only regex-scan the handful
        # of files that actually touch the helper.
        if "record_audit_fingerprint" not in text:
            continue
        # The call-site scan only flags *invocations*; the helper's own
        # definition in ``migration_harness.py`` is not a call site.
        if py.name == "migration_harness.py":
            continue
        for match in _CALL_SITE_RE.finditer(text):
            start = match.end()
            # Look ahead to the end of the call for a ``name=`` kwarg.
            window = text[start:start + 2000]
            name_match = _NAME_KW_RE.search(window)
            if name_match:
                out.append(
                    {
                        "path": str(py),
                        "name": name_match.group(1),
                    }
                )
    return out


def _existing_decision_records(decisions_dir: Path) -> Set[str]:
    if not decisions_dir.is_dir():
        return set()
    return {p.stem for p in decisions_dir.glob("*.md")}


_DECISION_RECORD_REF_RE = re.compile(
    r"docs/archive/decisions/([A-Za-z0-9_\-]+)\.md"
)


def _exception_reason_documented(
    reason: Optional[str], existing_records: Set[str]
) -> bool:
    """Return True when ``reason`` names an existing decision record.

    A populated ``exception_reason`` that references
    ``docs/archive/decisions/<slug>.md`` and the file is present on
    disk is the operator-authored disposition. The HC honors that
    pairing instead of warning indefinitely.
    """
    if not reason:
        return False
    for match in _DECISION_RECORD_REF_RE.finditer(reason):
        slug = match.group(1)
        if slug in existing_records:
            return True
    return False


def hc_oneshot_migration_coverage(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Scan for governed DB-mutation authoring drift and exception-path
    records that are missing a paired decision record."""
    issues: List[str] = []

    # Drift classes (a) and (b): items with non-default profiles.
    if _base._table_exists(conn, "items"):
        terminal_tuple = ",".join(f"'{s}'" for s in _TERMINAL_STATUSES)
        rows = query_rows(
            conn,
            f"SELECT id, db_mutation_profile, db_compatibility_attestation "
            f"FROM items "
            f"WHERE status NOT IN ({terminal_tuple}) "
            f"  AND db_mutation_profile IS NOT NULL "
            f"  AND db_mutation_profile <> '' "
            f"  AND db_mutation_profile <> 'null'",
        )
        for row in rows:
            item_id = int(row["id"])
            profile = _parse_json_field(row["db_mutation_profile"])
            if profile is None:
                issues.append(
                    f"- YOK-{item_id}: db_mutation_profile is present "
                    f"but not valid JSON; expected an object."
                )
                continue
            issues.extend(_profile_issues(item_id, profile))
            issues.extend(
                _attestation_issues(
                    item_id, profile, row["db_compatibility_attestation"]
                )
            )

    # Drift class (c): live call sites without paired decision records.
    repo_root = Path(_base._resolve_repo_root() or ".").resolve()
    api_root = repo_root / "runtime" / "api"
    decisions_dir = repo_root / "docs" / "archive" / "decisions"
    existing_records = _existing_decision_records(decisions_dir)

    call_sites = _scan_call_sites(api_root)
    seen: Set[str] = set()
    for site in call_sites:
        name = site["name"]
        if name in seen:
            continue
        seen.add(name)
        if name not in existing_records:
            rel = site["path"].replace(str(repo_root) + "/", "")
            issues.append(
                f"- record_audit_fingerprint call site '{name}' in "
                f"{rel} lacks paired decision record at "
                f"docs/archive/decisions/{name}.md."
            )

    # Drift class (d): audit rows with non-canonical ``backup_path``.
    # Empty paths are the explicit no-backup branch; populated paths
    # that don't match a canonical ``backups/*`` shape are pre-fix
    # exception-path rows that copied the DB to a non-canonical location.
    # A non-empty ``exception_reason`` whose text references
    # an existing ``docs/archive/decisions/<slug>.md`` record satisfies
    # the disposition requirement and the row is skipped — the
    # decision record IS the documented disposition. Rows without a
    # paired record are surfaced.
    if _base._table_exists(conn, "migration_audit"):
        audit_rows = query_rows(
            conn,
            "SELECT id, migration_name, backup_path, exception_reason "
            "FROM migration_audit "
            "WHERE backup_path IS NOT NULL "
            "  AND backup_path <> '' "
            "ORDER BY id",
        )
        for row in audit_rows:
            path = str(row["backup_path"] or "")
            if _CANONICAL_BACKUP_RE.search(path):
                continue
            if _exception_reason_documented(
                row["exception_reason"], existing_records
            ):
                continue
            issues.append(
                f"- migration_audit row {int(row['id'])} "
                f"({row['migration_name']}): non-canonical "
                f"backup_path {path!r}. Canonical shape is "
                f"'<repo>/.yoke/backups/postgres.YYYYMMDD-HHMMSS."
                f"<reason>.sql'. Pre-fix exception-path rows "
                f"may be left as-is; document the disposition "
                f"before advancing by authoring "
                f"docs/archive/decisions/<slug>.md and naming the "
                f"slug in exception_reason."
            )

    if issues:
        rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))
    else:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")

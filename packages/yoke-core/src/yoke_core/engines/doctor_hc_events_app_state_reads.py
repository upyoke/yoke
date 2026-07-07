"""HC-events-app-state-reads: events is telemetry-only — no app-state SQL reads.

Background
----------
The cloud-runtime cutover moved every application-state concept OUT of the events ledger
into dedicated tables/columns: ``function_call_ledger`` (dispatcher
idempotency), ``harness_sessions`` activity columns + ``session_tool_calls``
(liveness, lints, episode boundary), ``item_status_transitions`` +
``item_activity_days`` + ``strategy_checkpoints`` (board, exec status,
drift), ``work_claims`` reason columns + chain columns (frontier routing,
claim recovery), ``path_claim_overrides`` and the ``db_mutation_profile``
attestation (gates). After the telemetry-only events cutover, a runtime module that answers an
application-state question by scanning ``events`` re-inverts the
architecture: state would again depend on the telemetry pipeline and its
retention policy. This HC is the permanent backstop.

Contract
--------
Any non-test runtime Python file containing a SQL read of the events table
(``FROM events`` / ``JOIN events``) must be on the allowlist below. The
allowlist enumerates the sanctioned reader classes:

- **Telemetry-admin surfaces** — the events platform itself (queries,
  prune, registry audit, severity tooling, ledger-hygiene HCs).
- **Keep-as-audit doctor surfaces** — checks whose PURPOSE is verifying
  behavior against the telemetry record (the audit-inspection carve-out).
- **Emission-side capability probes** — write-path probes, not reads.
- **Governed migration backfills** — one-time history loads into the state
  tables (the ``migrations/`` prefix; modules retire after live apply).

Maintenance
-----------
A new legitimate telemetry/audit reader adds its path here in the same
commit, with the reader class named in the inline comment. Moving an
app-state read back onto events is never the fix — give the concept a
table owner. Stale entries (no longer matching) surface in the PASS detail
so retirements clean up their allowlist rows.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

# SQL read shapes against the events table. Line-based; covers aliased
# forms (``FROM events e``). INSERT shapes are emission discipline, not
# read inversion, and stay out of scope.
EVENTS_READ_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+events\b", re.IGNORECASE)

# Repo-relative allowlist. Prefix-matched, so a directory entry covers the
# subtree. Keep entries grouped by reader class.
_CORE_DOMAIN_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/domain"
_CORE_ENGINE_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/engines"
_CORE_TOOLS_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/tools"

ALLOWED_EVENTS_READERS: tuple[str, ...] = (
    # -- telemetry-admin: the events platform itself
    f"{_CORE_DOMAIN_SOURCE_ROOT}/events_queries.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/handlers/events_reads.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/events_audit_presets.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/events_prune.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/events_registry_audit.py",
    f"{_CORE_TOOLS_SOURCE_ROOT}/backfill_event_severity.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/observe_normalization.py",  # pipeline-internal duration join
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_db_catalog.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_db_events_emission.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_db_events_ledger.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_db_events_registry.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_event_outcome_drift.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_event_outcome_enum_coverage.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_event_severity_drift.py",
    # -- keep-as-audit: doctor surfaces that verify behavior against telemetry
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor.py",  # HarnessSessionEndDeferred audit listing
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_agents_sessions.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_stop_hook_chain.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_session_cwd_binding.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_path_claim_rejections.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_apply_patch.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_reflection_capture_hook_coverage.py",
    f"{_CORE_ENGINE_SOURCE_ROOT}/doctor_hc_reflection_capture_persist_failed.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/check_claim_boundary_audit_correlation.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/check_claim_boundary_audit_cutoff.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/check_claim_boundary_audit_select.py",
    # -- emission-side capability probes (SELECT 1 ... LIMIT 1)
    f"{_CORE_DOMAIN_SOURCE_ROOT}/epic_cascade.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/observe_event_emission.py",
    # -- teaching: telemetry-recipe SQL examples in the events packet entry
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_core.py",
    # -- governed one-time backfills (modules retire after live apply).
    # Legitimately empty at steady state (no migration in flight) — exempt
    # from the stale-entry check via _TRANSIENT_EMPTY_OK below.
    f"{_CORE_DOMAIN_SOURCE_ROOT}/migrations/",
)

# Allowlist prefixes that are legitimately empty between migrations: a
# governed backfill module reads events transiently, then retires after
# live apply. These are structural reader classes, not retirement residue,
# so they are never reported stale even when no file currently matches.
_TRANSIENT_EMPTY_OK: frozenset[str] = frozenset(
    {f"{_CORE_DOMAIN_SOURCE_ROOT}/migrations/"}
)

_SELF_PATH = Path(__file__).resolve()


def _is_scan_target(path: Path) -> bool:
    """Live runtime Python only: no tests, fixtures, or this registry."""
    if path.name.startswith("test_") or path.name == "conftest.py":
        return False
    # Test-support modules (shared helpers/schemas for suites) follow the
    # ``*_test_helpers.py`` / ``*_test_schema.py`` naming shapes.
    if "_test_" in path.name:
        return False
    if path.resolve() == _SELF_PATH or path.name == _SELF_PATH.name:
        return False
    if "fixtures" in path.parts:
        return False
    return True


def _allowlisted(rel_str: str) -> bool:
    return any(rel_str.startswith(entry) for entry in ALLOWED_EVENTS_READERS)


def scan_events_reads(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (violations, stale_allowlist_entries) for ``repo_root``.

    Violations are ``path:line: text`` strings for events reads outside the
    allowlist. Stale entries are allowlist rows that matched no file with a
    read — retirement residue the owner should drop.
    """
    violations: list[str] = []
    matched_entries: set[str] = set()
    for source_root in (repo_root / "runtime", repo_root / "packages"):
        if not source_root.is_dir():
            continue
        for f in sorted(source_root.rglob("*.py")):
            if not _is_scan_target(f):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not EVENTS_READ_PATTERN.search(text):
                continue
            try:
                rel = f.resolve().relative_to(repo_root.resolve())
            except ValueError:
                rel = f
            rel_str = str(rel)
            if _allowlisted(rel_str):
                for entry in ALLOWED_EVENTS_READERS:
                    if rel_str.startswith(entry):
                        matched_entries.add(entry)
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if EVENTS_READ_PATTERN.search(line):
                    violations.append(f"{rel_str}:{i}: {line.strip()[:160]}")
    stale = [
        e
        for e in ALLOWED_EVENTS_READERS
        if e not in matched_entries and e not in _TRANSIENT_EMPTY_OK
    ]
    return violations, stale


def hc_events_app_state_reads(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-events-app-state-reads: events reads outside the telemetry allowlist."""
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(
            "HC-events-app-state-reads",
            "Events table reads outside telemetry allowlist",
            "PASS",
            "No repo root resolved — skipping.",
        )
        return
    violations, stale = scan_events_reads(Path(repo_root_str))
    if violations:
        rec.record(
            "HC-events-app-state-reads",
            "Events table reads outside telemetry allowlist",
            "FAIL",
            "events is telemetry-only post telemetry-only-events; give the concept a table owner "
            "(see yoke_core.engines.doctor_hc_events_app_state_reads "
            "docstring) or add a sanctioned reader-class allowlist entry.\n"
            + "\n".join(violations[:40]),
        )
        return
    detail = ""
    if stale:
        detail = "Stale allowlist entries (no events read found): " + ", ".join(stale)
    rec.record(
        "HC-events-app-state-reads",
        "Events table reads outside telemetry allowlist",
        "PASS",
        detail,
    )

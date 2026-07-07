"""Shared QA vocabulary constants and tiny normalizers.

Leaf module owned by the QA domain. Imported by both ``qa_requirements`` and
``qa_execution`` parent shims and their focused sibling modules. Keeping
these symbols in a leaf module prevents import cycles between the parent
shims and the ops modules.

This module deliberately imports nothing from any ``yoke_core.domain.qa*``
sibling. Its only allowed dependencies are the standard library.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence


# ---------------------------------------------------------------------------
# Canonical QA vocabulary tuples
# ---------------------------------------------------------------------------

VALID_QA_PHASES = ("verification", "post_deploy", "manual_acceptance")
VALID_BLOCKING_MODES = ("blocking", "non_blocking")
VALID_REQUIREMENT_SOURCES = ("explicit", "seeded_default", "ac_derived", "flow_derived")
VALID_VERDICTS = ("pass", "fail", "inconclusive", "error")
VALID_BROWSER_QA_KINDS = ("browser_smoke", "browser_diff")


# ---------------------------------------------------------------------------
# Tiny shared formatting helpers
# ---------------------------------------------------------------------------

def _coalesce(val: Any, default: str = "") -> str:
    """Return *val* as a string, or *default* when None."""
    if val is None:
        return default
    return str(val)


def _normalize_qa_phase(qa_phase: str) -> str:
    """Normalize retired qa_phase values to canonical vocab."""
    _phase_map = {"validation": "verification"}
    return _phase_map.get(qa_phase, qa_phase)


def _normalize_qa_kind(qa_kind: str) -> str:
    """Normalize retired qa_kind values to canonical vocab."""
    _kind_map = {"review": "implementation_review"}
    return _kind_map.get(qa_kind, qa_kind)


def _pipe_row(row, cols: Optional[Sequence[str]] = None) -> str:
    if cols:
        return "|".join(_coalesce(row[c]) for c in cols)
    return "|".join(_coalesce(v) for v in row)


# ---------------------------------------------------------------------------
# Canonical SELECT column list for qa_requirements rows
# ---------------------------------------------------------------------------

# Canonical qa_requirements column roster. ``_REQ_SELECT`` below is the
# pipe-format CLI projection of exactly these columns (with COALESCE/CAST
# presentation); the typed function-call handlers select the same roster
# natively. Keep the two adjacent definitions in lockstep.
REQ_COLUMNS = (
    "id", "item_id", "epic_id", "task_num", "deployment_run_id",
    "qa_kind", "qa_phase", "target_env", "blocking_mode",
    "requirement_source", "success_policy", "capability_requirements",
    "suite_id", "waived_at", "waiver_rationale", "waiver_source",
    "created_at",
)

_REQ_SELECT = (
    "id, COALESCE(CAST(item_id AS TEXT),''), COALESCE(CAST(epic_id AS TEXT),''), "
    "COALESCE(CAST(task_num AS TEXT),''), "
    "COALESCE(deployment_run_id,''), qa_kind, qa_phase, COALESCE(target_env,''), "
    "blocking_mode, requirement_source, COALESCE(success_policy,''), "
    "COALESCE(capability_requirements,''), COALESCE(suite_id,''), "
    "COALESCE(waived_at,''), COALESCE(waiver_rationale,''), "
    "COALESCE(waiver_source,''), created_at"
)


# Canonical qa_runs column roster for typed reads. Superset note:
# ``qa_execution._RUN_SELECT`` (the pipe-format CLI projection) predates
# ``execution_status`` and omits it; the typed surface includes it because
# the browser-QA capture flow branches on it.
RUN_COLUMNS = (
    "id", "qa_requirement_id", "executor_type", "qa_kind", "verdict",
    "execution_status", "score", "confidence", "raw_result", "duration_ms",
    "started_at", "completed_at", "created_at",
)

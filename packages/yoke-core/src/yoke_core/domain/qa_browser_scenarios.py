"""Browser scenario policy and metadata-driven requirement seeding.

Sibling module to ``qa_requirements`` owned by the QA domain. Hosts the
browser-scenario-specific helpers (settle-delay floor, scenario policy
builder, ``browser_qa_metadata``-driven requirement batch construction) so
the parent ``qa_requirements`` shim stays focused on the requirement-add
CRUD surfaces.

The lazy imports inside :func:`read_browser_qa_metadata` are intentional:
the ``yoke_core.domain.items`` and ``yoke_core.domain.browser_qa_metadata``
modules sit higher in the import graph and would create cycles if pulled in
at module import time.

Callers can import the browser scenario helpers through
``from yoke_core.domain.qa_requirements import build_browser_scenario_policy``
because the parent shim re-exports every public symbol below.
"""

from __future__ import annotations

import json
from typing import List, Optional


# ---------------------------------------------------------------------------
# Settle-delay floor
# ---------------------------------------------------------------------------

# Floor in milliseconds for the settle delay inserted between the first
# ``navigate`` step and the first ``screenshot`` step. Anything shorter risks
# capturing auth spinners, skeleton loaders, or pre-hydration font swaps
# instead of the real render.
DEFAULT_SETTLE_MS = 2000


def min_delay_before_first_screenshot(timing_hint_ms: Optional[int] = None) -> int:
    """Return the settle-delay floor applied before the first screenshot.

    The final pre-screenshot delay is ``max(DEFAULT_SETTLE_MS, timing_hint_ms)``.
    A timing hint below the floor is raised to the floor; a hint above the floor
    replaces it (no stacking). ``None`` means no hint and returns the floor.
    """
    if timing_hint_ms is None:
        return DEFAULT_SETTLE_MS
    return max(DEFAULT_SETTLE_MS, int(timing_hint_ms))


def _inject_settle_delay(steps: List[dict], *, floor_ms: int) -> List[dict]:
    """Return a new steps list with a settle delay enforced before the first
    screenshot following the first navigate.

    - If a ``delay`` step already sits between the navigate and the screenshot,
      its ``duration`` is raised to ``floor_ms`` when the existing value is
      smaller. Values at or above the floor are preserved so AC-derived timing
      hints (e.g., 7000ms for a confetti assertion) keep their specificity.
    - If no intervening delay exists, one is inserted immediately before the
      screenshot with ``duration=floor_ms``. The injected step is marked
      ``source_ac="settle-floor"`` for traceability.
    """
    if floor_ms <= 0:
        return list(steps)

    out = list(steps)

    nav_idx: Optional[int] = None
    for i, step in enumerate(out):
        if isinstance(step, dict) and step.get("action") == "navigate":
            nav_idx = i
            break
    if nav_idx is None:
        return out

    shot_idx: Optional[int] = None
    for i in range(nav_idx + 1, len(out)):
        step = out[i]
        if isinstance(step, dict) and step.get("action") == "screenshot":
            shot_idx = i
            break
    if shot_idx is None:
        return out

    delay_idx: Optional[int] = None
    for i in range(nav_idx + 1, shot_idx):
        step = out[i]
        if isinstance(step, dict) and step.get("action") == "delay":
            delay_idx = i
            break

    if delay_idx is not None:
        existing_step = out[delay_idx]
        existing_duration = existing_step.get("duration")
        if existing_duration is None:
            existing_duration = existing_step.get("duration_ms", 0)
        try:
            existing_ms = int(existing_duration or 0)
        except (TypeError, ValueError):
            existing_ms = 0
        if existing_ms < floor_ms:
            updated = dict(existing_step)
            updated["duration"] = floor_ms
            updated.setdefault("source_ac", "settle-floor")
            out[delay_idx] = updated
    else:
        out.insert(
            shot_idx,
            {
                "action": "delay",
                "duration": floor_ms,
                "refined": False,
                "source_ac": "settle-floor",
            },
        )

    return out


def build_browser_scenario_policy(
    base_url: str,
    steps: List[dict],
    *,
    default_settle_ms: int = DEFAULT_SETTLE_MS,
) -> str:
    """Build a properly JSON-encoded browser scenario success_policy string.

    The function enforces the pre-screenshot settle-delay floor defined by
    :func:`min_delay_before_first_screenshot`: every ``navigate`` → …→
    ``screenshot`` sequence ends up with at least ``default_settle_ms``
    milliseconds between the navigate and the screenshot. AC-derived timing
    hints larger than the floor replace it (no stacking).

    Pass ``default_settle_ms=0`` to disable the injection for callers that
    must preserve the exact step list unchanged (e.g., regression fixtures).

    Avoids shell escaping issues by using Python's json module. Returns the
    JSON string ready for use as a ``success_policy`` value in
    ``requirement-add`` or ``requirement-add-batch`` payloads.
    """
    effective_steps = _inject_settle_delay(steps, floor_ms=default_settle_ms)
    return json.dumps({
        "type": "browser_scenario",
        "base_url": base_url,
        "steps": effective_steps,
    })


# ---------------------------------------------------------------------------
# browser_qa_metadata-driven scenario building
# ---------------------------------------------------------------------------

def read_browser_qa_metadata(
    item_id: int,
    *,
    db_path: Optional[str] = None,
    conn=None,
) -> dict:
    """Return the validated browser_qa_metadata object for *item_id*.

    Reads the structured field through :mod:`yoke_core.domain.items` and
    routes it through the validator so callers always see a normalized dict.
    If the field is missing, empty, or literally ``"null"``, returns a fresh
    copy of :data:`yoke_core.domain.browser_qa_metadata.NEGATIVE_DEFAULT` so
    downstream consumers never have to special-case the unset state.

    Raises :class:`yoke_core.domain.browser_qa_metadata.BrowserQaMetadataError`
    only when the stored payload is present but malformed or schema-invalid —
    that state is a data integrity bug, not a migration gap, and callers must
    surface it rather than silently fall back.
    """
    from yoke_core.domain.browser_qa_metadata import (
        negative_default,
        validate,
    )
    from yoke_core.domain.items import query_item

    raw = query_item(item_id, "browser_qa_metadata", db_path=db_path)
    if raw is None or raw == "" or raw == "null":
        return negative_default()
    payload = json.loads(raw)
    return validate(payload)


def build_browser_requirements_from_metadata(
    item_id: int,
    base_url: str,
    *,
    db_path: Optional[str] = None,
    requirement_source: str = "seeded_default",
    include_diff: bool = False,
) -> List[dict]:
    """Return a list of qa_requirement row dicts derived from metadata.

    Non-browser items (``browser_testable=false``) return ``[]``. For browser
    items, one ``browser_smoke`` row is emitted per route plus one additional
    row per AC-derived timing hint so multi-capture scenarios keep distinct
    success policies. When ``include_diff`` is true and ``visual_outcome`` is
    set, a ``browser_diff`` row is also emitted per route — callers that need
    the richer "baseline already exists" check can gate this flag themselves.

    The returned dicts share the ``requirement_add_batch`` shape so the caller
    can pass the list directly to :func:`cmd_requirement_add_batch`. The
    resulting rows carry the canonical ``type=browser_scenario`` success_policy
    produced by :func:`build_browser_scenario_policy`, which includes the
    pre-screenshot settle-delay floor.
    """
    metadata = read_browser_qa_metadata(item_id, db_path=db_path)
    if not metadata["browser_testable"]:
        return []

    routes: List[str] = list(metadata["browser_routes"])
    if not routes:
        routes = ["/"]

    timings: List[int] = list(metadata["browser_timing_hints_ms"])
    rows: List[dict] = []

    for route in routes:
        base_steps = [
            {"action": "navigate", "route": route, "refined": False,
             "source_ac": "setup"},
            {"action": "screenshot", "capture": True, "refined": False},
        ]
        rows.append({
            "item_id": item_id,
            "qa_kind": "browser_smoke",
            "qa_phase": "verification",
            "blocking_mode": "blocking",
            "requirement_source": requirement_source,
            "success_policy": build_browser_scenario_policy(base_url, base_steps),
        })

        for hint_ms in timings:
            timed_steps = [
                {"action": "navigate", "route": route, "refined": False,
                 "source_ac": "setup"},
                {"action": "delay", "duration": hint_ms, "refined": False,
                 "source_ac": "timing"},
                {"action": "screenshot", "capture": True, "refined": False},
            ]
            rows.append({
                "item_id": item_id,
                "qa_kind": "browser_smoke",
                "qa_phase": "verification",
                "blocking_mode": "blocking",
                "requirement_source": requirement_source,
                "success_policy": build_browser_scenario_policy(
                    base_url, timed_steps,
                ),
            })

        if include_diff and metadata["visual_outcome"]:
            diff_steps = [
                {"action": "navigate", "route": route, "refined": False},
                {"action": "screenshot", "capture": True, "refined": False},
            ]
            rows.append({
                "item_id": item_id,
                "qa_kind": "browser_diff",
                "qa_phase": "verification",
                "blocking_mode": "blocking",
                "requirement_source": requirement_source,
                "success_policy": build_browser_scenario_policy(
                    base_url, diff_steps,
                ),
            })

    return rows

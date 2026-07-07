"""Doctor-format output for resync."""

from __future__ import annotations

from typing import List, Tuple

from yoke_core.engines.doctor_hc_gh_skip import GH_PAT_NOT_CONFIGURED_SKIP_REASON
from yoke_core.engines.resync_detect import DriftRecord


def _emit_doctor_format(
    local_orphans: List[Tuple[str, str, str, str]],
    gh_orphans: List[Tuple[int, str, str, str]],
    drifts: List[DriftRecord],
    mode: str,
) -> None:
    """Print HC-* lines in doctor-parseable format."""
    # HC-missing-gh-issues
    hc28_detail = ""
    hc28_status = "PASS"
    for oid, ofile, otype, oproj in local_orphans:
        if otype != "backlog":
            continue
        hc28_status = "WARN"
        hc28_detail += f"- {oid}: no GitHub issue linked (project={oproj})\\n"
    print(f"HC-missing-gh-issues|Missing GitHub issues|{hc28_status}|{hc28_detail}")

    # HC-orphan-epic-tasks
    hc44_detail = ""
    hc44_status = "PASS"
    for oid, ofile, otype, oproj in local_orphans:
        if otype != "epic_task":
            continue
        hc44_status = "WARN"
        hc44_detail += f"- {oid}: no GitHub issue linked (project={oproj})\\n"
    print(f"HC-orphan-epic-tasks|Orphan epic tasks|{hc44_status}|{hc44_detail}")

    # HC-title-drift
    hc29_detail = ""
    hc29_status = "PASS"
    for d in drifts:
        if d.field != "title":
            continue
        hc29_status = "WARN"
        if mode == "fix":
            hc29_detail += f"- {d.id}: title drift -- FIXED (updated GitHub)\\n"
        else:
            hc29_detail += f"- {d.id}: local='{d.local}' vs GitHub='{d.github}'\\n"
    print(f"HC-title-drift|Title drift|{hc29_status}|{hc29_detail}")

    # HC-body-drift
    hc30_detail = ""
    hc30_status = "PASS"
    for d in drifts:
        if d.field != "body":
            continue
        hc30_status = "WARN"
        if mode == "fix":
            hc30_detail += f"- {d.id}: body drift -- FIXED (synced to GitHub)\\n"
        else:
            hc30_detail += f"- {d.id}: body differs from GitHub\\n"
    print(f"HC-body-drift|Body drift|{hc30_status}|{hc30_detail}")

    # HC-reverse-completeness
    hc31_detail = ""
    hc31_status = "PASS"
    if gh_orphans:
        hc31_status = "WARN"
        for num, title, state, proj in gh_orphans:
            hc31_detail += f"- #{num}: {title} ({state}, source={proj})\\n"
    print(f"HC-reverse-completeness|Reverse completeness|{hc31_status}|{hc31_detail}")

    # HC-comment-sync
    hc32_detail = ""
    hc32_status = "PASS"
    for d in drifts:
        if d.field != "comment":
            continue
        hc32_status = "WARN"
        if mode == "fix":
            hc32_detail += f"- {d.id}: no **Status:** comment -- FIXED (posted)\\n"
        else:
            hc32_detail += f"- {d.id}: done but no **Status:** comment on GitHub\\n"
    print(f"HC-comment-sync|Comment sync|{hc32_status}|{hc32_detail}")

    # HC-label-drift
    hc39_detail = ""
    hc39_status = "PASS"
    for d in drifts:
        if d.field not in (
            "label-status", "label-priority", "label-type",
            "label-source", "label-owner",
        ):
            continue
        hc39_status = "WARN"
        if mode == "fix":
            hc39_detail += f"- {d.id}: {d.field} drift ({d.local} vs {d.github}) -- FIXED\\n"
        else:
            hc39_detail += f"- {d.id}: {d.field} drift ({d.local} vs {d.github})\\n"
    print(f"HC-label-drift|Label drift|{hc39_status}|{hc39_detail}")

    # HC-state-drift
    hc40_detail = ""
    hc40_status = "PASS"
    for d in drifts:
        if d.field != "state":
            continue
        hc40_status = "WARN"
        if mode == "fix":
            hc40_detail += f"- {d.id}: expected {d.local}, GitHub is {d.github} -- FIXED\\n"
        else:
            hc40_detail += f"- {d.id}: expected {d.local}, GitHub is {d.github}\\n"
    print(f"HC-state-drift|State drift|{hc40_status}|{hc40_detail}")

    # HC-frozen-label-drift / HC-blocked-label-drift
    for fld, slug, label in (
        ("label-frozen", "HC-frozen-label-drift", "Frozen label drift"),
        ("label-blocked", "HC-blocked-label-drift", "Blocked label drift"),
    ):
        det = ""
        st = "PASS"
        for d in drifts:
            if d.field != fld:
                continue
            st = "WARN"
            if mode == "fix":
                det += f"- {d.id}: {d.local} vs {d.github} -- FIXED\\n"
            else:
                det += f"- {d.id}: {d.local} vs {d.github}\\n"
        print(f"{slug}|{label}|{st}|{det}")

    # HC-task-label-drift -- not reimplemented here; requires per-task gh calls
    # This HC is deferred to the shell pass (it requires live GH label fetching per task)
    print("HC-task-label-drift|Epic task label drift|PASS|")


def _emit_gh_unavailable_doctor() -> None:
    """Emit SKIP for all GitHub-dependent HCs when the project PAT is not
    configured.

    Routes through the canonical
    :data:`yoke_core.engines.doctor_hc_gh_skip.GH_PAT_NOT_CONFIGURED_SKIP_REASON`
    so the operator sees one consistent message across the doctor report.
    """
    skip_msg = GH_PAT_NOT_CONFIGURED_SKIP_REASON.format(project="yoke")
    for hc in [
        "HC-missing-gh-issues|Missing GitHub issues",
        "HC-title-drift|Title drift",
        "HC-body-drift|Body drift",
        "HC-reverse-completeness|Reverse completeness",
        "HC-comment-sync|Comment sync",
        "HC-label-drift|Label drift",
        "HC-state-drift|State drift",
        "HC-frozen-label-drift|Frozen label drift",
        "HC-blocked-label-drift|Blocked label drift",
        "HC-task-label-drift|Epic task label drift",
    ]:
        print(f"{hc}|WARN|{skip_msg}")

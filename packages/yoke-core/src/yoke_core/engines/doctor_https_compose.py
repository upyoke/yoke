"""Compose LOCAL source-tree doctor checks with relayed control-plane ones.

An https client holds the checkout the hosted runner does not. Relayed
``doctor.run.run`` correctly N/As ``requires_source_checkout`` checks on
the server; this module re-runs those checks on the client and merges
them into one report so a machine with a checkout does not report false
not-applicable rows for trees it can read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from yoke_core.domain.control_plane_transport import local_connection_or_none
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_checkout_locations import (
    checkout_for_project_id,
    checkout_for_project_slug,
)
from yoke_core.engines.doctor_applicability import RUNTIME_LOCAL
from yoke_core.engines.doctor_applicability_declarations import (
    source_checkout_slugs,
)
from yoke_core.engines.doctor_check_execution import execute_check_isolated
from yoke_core.engines.doctor_registry import HEALTH_CHECKS
from yoke_core.engines.doctor_report import (
    CheckResult,
    DoctorArgs,
    RecordCollector,
)
from yoke_core.engines.doctor_source_root import bound_source_root


_NO_CHECKOUT_DETAIL = "this runner has no checkout for it"


def checkout_root_for_project(project: str) -> Optional[Path]:
    """Machine-local checkout for *project* (id or slug), if one is mapped."""
    text = str(project or "").strip()
    if not text:
        return None
    if text.isdigit():
        root = checkout_for_project_id(int(text))
    else:
        root = checkout_for_project_slug(text)
    if root is None:
        return None
    path = Path(root)
    return path if path.is_dir() else None


def machine_has_checkout_for(project: str) -> bool:
    """True when this machine maps *project* (id or slug) to a checkout."""
    return checkout_root_for_project(project) is not None


def false_na_source_slugs(results: Sequence[Dict[str, Any]]) -> List[str]:
    """Slugs reported N/A solely because the relayed runner lacked a checkout.

    Prefer declared source-checkout slugs, but also heal older control-plane
    builds that still stamp the checkout N/A detail on checks this client
    no longer classifies as source-only.
    """
    wanted = source_checkout_slugs()
    out: List[str] = []
    seen: set[str] = set()
    for row in results:
        hc = str(row.get("hc") or "")
        slug = hc[3:] if hc.startswith("HC-") else hc
        if str(row.get("severity") or "").upper() != "N/A":
            continue
        if _NO_CHECKOUT_DETAIL not in str(row.get("detail") or ""):
            continue
        if slug not in wanted and not slug:
            continue
        # Heal any checkout-gap N/A when this machine holds the tree.
        if slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return out


def note_missing_control_plane(
    records: Sequence[CheckResult],
    project: str,
) -> None:
    """Rewrite DB-dependent FAILs as N/A when no local control plane exists.

    A checkout-holding https client can read the tree but has no
    local-postgres authority, so the DB half of a mixed check fails for a
    reason that says nothing about the project. Reporting that as a
    failure would be a lie; reporting it as not-applicable, with the
    reason, is the honest answer.
    """
    for record in records:
        if record.result != "FAIL":
            continue
        if "no local control-plane" not in (record.detail or ""):
            continue
        record.result = "N/A"
        record.detail = (
            f"reads the {project} source tree and needs "
            "control-plane rows; this https client has the "
            "checkout but no local-postgres authority for "
            "the DB half of the check"
        )


def run_local_source_checks(
    *,
    project: str,
    quick: bool,
    full: bool,
    fix: bool,
    only: Optional[str],
    slugs: Sequence[str],
) -> List[Dict[str, Any]]:
    """Execute the named source-checkout HCs against *project*'s checkout.

    The checks read the tree mapped for the selected project, not whatever
    tree the caller happens to stand in, so ``--project buzz`` run from the
    Yoke checkout cannot report Yoke findings under the Buzz label. Without
    a mapped checkout there is no tree to read and the relayed
    not-applicable verdicts stand.
    """
    if not slugs:
        return []
    root = checkout_root_for_project(project)
    if root is None:
        return []
    wanted = set(slugs)
    args = DoctorArgs(
        only=",".join(sorted(wanted)),
        quick=quick,
        project=str(project),
        fix=fix,
        runtime=RUNTIME_LOCAL,
    )
    # Scope flags for roster filtering when only= is set; still pass through.
    del full
    rec = RecordCollector()
    conn = local_connection_or_none(connect)
    owned = conn is not None
    if conn is None:
        # FS-oriented checks often ignore conn; DB-touching ones fail isolated
        # and record FAIL — convert those to honest N/A below.
        conn = UnavailableControlPlane()
    try:
        with bound_source_root(root):
            for hc in HEALTH_CHECKS:
                if hc.slug not in wanted:
                    continue
                pre = len(rec.results)
                execute_check_isolated(conn, args, rec, hc)
                if not owned:
                    note_missing_control_plane(rec.results[pre:], project)
    finally:
        if owned:
            try:
                conn.close()
            except Exception:
                pass
    return [
        {
            "hc": r.check_id,
            "name": r.check_name,
            "severity": r.result,
            "detail": r.detail,
        }
        for r in rec.results
    ]


def _hc_key(value: object) -> str:
    text = str(value or "")
    return text[3:] if text.startswith("HC-") else text


def merge_relayed_with_local(
    relayed_results: Sequence[Dict[str, Any]],
    local_results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Replace false checkout N/A rows with locally executed verdicts."""
    by_slug = {
        _hc_key(row.get("hc")): row
        for row in local_results
        if row.get("hc")
    }
    merged: List[Dict[str, Any]] = []
    replaced: set[str] = set()
    for row in relayed_results:
        slug = _hc_key(row.get("hc"))
        local = by_slug.get(slug)
        if (
            local is not None
            and str(row.get("severity") or "").upper() == "N/A"
            and _NO_CHECKOUT_DETAIL in str(row.get("detail") or "")
        ):
            merged.append(dict(local))
            replaced.add(slug)
        else:
            merged.append(dict(row))
    for slug, row in by_slug.items():
        if slug not in replaced:
            merged.append(dict(row))
    return merged


def recount(results: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    fail = warn = passed = na = 0
    for row in results:
        severity = str(row.get("severity") or "").upper()
        if severity == "FAIL":
            fail += 1
        elif severity == "WARN":
            warn += 1
        elif severity == "N/A":
            na += 1
        elif severity in {"PASS", "SKIP"}:
            passed += 1
    return {
        "fail_count": fail,
        "warn_count": warn,
        "pass_count": passed,
        "na_count": na,
    }


class UnavailableControlPlane:
    """Stand-in connection when the client has a checkout but no local DB."""

    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("no local control-plane database")

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def resolve_operator_project(project: str) -> str:
    """Prefer a slug when *project* is a numeric id string.

    Machine checkout defaults often yield ``str(project_id)``. Doctor HCs
    and operator output read better with the slug; numeric ids still work
    once ``HC-project-lookup`` uses ``resolve_project_id``, but resolving
    here also helps older control-plane builds.
    """
    text = str(project or "").strip()
    if not text or not text.isdigit():
        return text or project
    try:
        from yoke_core.domain.control_plane_transport import relay

        row = relay("projects.get", {"project": text}).get("row") or {}
        slug = str(row.get("slug") or "").strip()
        return slug or text
    except Exception:  # noqa: BLE001 - keep the numeric id if relay fails
        return text


__all__ = [
    "UnavailableControlPlane",
    "checkout_root_for_project",
    "false_na_source_slugs",
    "machine_has_checkout_for",
    "merge_relayed_with_local",
    "note_missing_control_plane",
    "recount",
    "resolve_operator_project",
    "run_local_source_checks",
]

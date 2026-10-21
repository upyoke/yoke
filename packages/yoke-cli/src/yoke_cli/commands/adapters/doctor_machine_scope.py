"""Doctor checks a caller can run from a folder outside every project.

Machine-scope checks read only this machine's state — harness homes,
machine hooks, the relay, connections — so they need no project. When
``yoke doctor run`` resolves no project, this module runs the requested
machine-scope checks here and reports every other requested check as not
applicable with the recovery that selects a project. A request with no
machine-scope check at all still refuses ``project_required``.

Client packages must not take a static ``yoke_core`` import, so the engine
is loaded dynamically, the same boundary ``doctor_install`` follows.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Iterable, List

from yoke_contracts.api.function_call import FunctionCallResponse


PROJECT_SKIP_DETAIL = (
    "project_required: this check runs against a project and none is "
    "selected here. Rerun from a project folder or add `--project P` "
    "(`yoke projects list` names P)."
)
PROJECT_CHECKS_SLUG = "project-checks"
PROJECT_CHECKS_NAME = "Project-scope checks"


def machine_scope_slugs() -> frozenset[str]:
    return importlib.import_module(
        "yoke_core.engines.doctor_applicability_declarations"
    ).machine_scope_slugs()


def requested_slugs(only: str) -> List[str]:
    """``--only`` tokens as bare slugs, in request order, without repeats."""
    slugs: List[str] = []
    for raw in only.split(","):
        slug = raw.strip().removeprefix("HC-")
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def machine_scope_rows(
    slugs: Iterable[str], *, quick: bool, fix: bool, only: str | None
) -> List[Dict[str, Any]]:
    """Run the machine-scope *slugs*; name every other one as skipped."""
    machine = machine_scope_slugs()
    requested = list(slugs)
    compose = importlib.import_module("yoke_core.engines.doctor_https_compose")
    rows = compose.run_local_runtime_checks(
        project="",
        quick=quick,
        fix=fix,
        slugs=[slug for slug in requested if slug in machine],
        only=only,
    )
    rows.extend(
        {
            "hc": f"HC-{slug}",
            "name": slug,
            "severity": "N/A",
            "detail": PROJECT_SKIP_DETAIL,
        }
        for slug in requested
        if slug not in machine
    )
    return rows


def run_without_project(
    *, slugs: List[str] | None, quick: bool, fix: bool, refusal: str
) -> tuple[FunctionCallResponse | None, str]:
    """The no-project doctor response, or ``None`` and the refusal text.

    *slugs* is the explicit roster (``--only``, ``--install``,
    ``--session``); ``None`` means ``--quick`` / ``--full``, whose roster
    is every machine-scope check plus one row naming the project checks.
    """
    machine = machine_scope_slugs()
    if slugs is None:
        rows = machine_scope_rows(sorted(machine), quick=quick, fix=fix, only=None)
        rows.append(
            {
                "hc": f"HC-{PROJECT_CHECKS_SLUG}",
                "name": PROJECT_CHECKS_NAME,
                "severity": "N/A",
                "detail": PROJECT_SKIP_DETAIL,
            }
        )
    elif not any(slug in machine for slug in slugs):
        return None, (
            f"{refusal} Every requested check runs against a project: "
            f"{', '.join(slugs)}."
        )
    else:
        rows = machine_scope_rows(slugs, quick=quick, fix=fix, only=",".join(slugs))
    compose = importlib.import_module("yoke_core.engines.doctor_https_compose")
    result: Dict[str, Any] = {
        "results": rows,
        **compose.recount(rows),
        "scope": "only" if slugs is not None else ("quick" if quick else "full"),
        "project": None,
        "runtime": "local",
        "composed": "machine_scope",
    }
    return (
        FunctionCallResponse(
            success=True,
            function="doctor.run.run",
            version="v1",
            request_id="",
            result=result,
        ),
        "",
    )


__all__ = [
    "PROJECT_SKIP_DETAIL",
    "machine_scope_rows",
    "machine_scope_slugs",
    "requested_slugs",
    "run_without_project",
]

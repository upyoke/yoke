"""Admit remote pytest iteration without duplicating a registered full CI gate."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import verification_tree_binding
from yoke_core.domain.project_verification_posture import REGISTERED_COMMAND_PLAN_PREFIX
from yoke_core.tools.impacted_project_test_roots import resolve_test_roots


def _config(raw: object) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _full_gate(project: str) -> dict | None:
    response = call_dispatcher(
        function_id="qa.plan.get",
        target=TargetRef(kind="global"),
        payload={
            "project": project,
            "plan_id": REGISTERED_COMMAND_PLAN_PREFIX + "full",
            "detail": "full",
        },
    )
    if not response.success:
        return None
    plan = (response.result or {}).get("plan") or {}
    if plan.get("retired_at"):
        return None
    for case in plan.get("cases") or []:
        config = _config(case.get("method_config"))
        if (
            case.get("method_id") == "command-ci"
            and config.get("registered_scope") == "full"
            and str(config.get("ci_workflow") or "").strip()
        ):
            return config
    return None


def _recovery(root: Path, project: str, gate: dict) -> str:
    lookup = verification_tree_binding.resolve_claim_worktrees(
        verification_tree_binding.ambient_session_id()
    )
    item = lookup.lane_item_id
    if (
        item
        and lookup.worktrees
        and Path(lookup.worktrees[0]).resolve() == root.resolve()
    ):
        response = call_dispatcher(
            function_id="qa.requirement.list",
            target=TargetRef(kind="item", public_ref=item),
            payload={},
        )
        if response.success:
            for row in (response.result or {}).get("rows") or []:
                config = _config(row.get("method_config"))
                if (
                    row.get("method_id") == "command-ci"
                    and config.get("ci_workflow") == gate["ci_workflow"]
                    and config.get("registered_scope") in {"full", "quick"}
                    and row.get("qa_phase") != "post_deploy"
                    and not row.get("waived_at")
                    and not row.get("replacement_requirement_id")
                    and not row.get("deployment_run_id")
                    and not row.get("superseded_by_requirement_id")
                    and row.get("id")
                ):
                    return f"yoke qa case run --requirement-id {int(row['id'])}"
        return f"yoke qa requirement list --item {shlex.quote(item)}"
    return (
        "yoke qa plan get "
        + REGISTERED_COMMAND_PLAN_PREFIX
        + "full"
        + f" --project {shlex.quote(project)}"
    )


def full_scope_refusal(root: Path, project: str, args: Sequence[str]) -> str | None:
    """Refuse only proven complete, unfiltered coverage with an available gate."""
    # Import lazily: the CI runner shares the watcher's argument interpretation.
    from yoke_core.tools.ci_selection_run import positional_args
    from yoke_core.tools._watch_pytest_selection_diagnostics import selection_filters

    if any(
        arg
        in {
            "--collect-only",
            "--co",
            "--deselect",
            "--ignore",
            "--ignore-glob",
            "--lf",
            "--last-failed",
            "--sw",
            "--stepwise",
            "--sw-skip",
            "--stepwise-skip",
            "--sw-reset",
            "--stepwise-reset",
            "--splits",
        }
        or arg.startswith(("--deselect=", "--ignore=", "--ignore-glob=", "--splits="))
        for arg in args
    ):
        return None
    filters = selection_filters(args)
    if any(value.strip() for value in filters.values()):
        return None
    targets = positional_args(args)
    if not targets:
        # Pytest configuration chooses testpaths; declared roots alone cannot
        # prove what a no-operand invocation collects.
        return None
    paths = [
        root / target
        for target in targets
        if "::" not in target and (root / target).is_dir()
    ]
    if not paths:
        return None
    roots = resolve_test_roots(str(root.resolve()))
    if not roots:
        return None
    if not all(
        any((root / anchor).resolve().is_relative_to(path.resolve()) for path in paths)
        for anchor in roots
    ):
        return None
    try:
        gate = _full_gate(project)
    except Exception:  # noqa: BLE001 — an unreadable gate is not proven available
        return None
    if gate is None:
        return None
    try:
        recovery = _recovery(root, project, gate)
    except Exception:  # noqa: BLE001 — recovery lookup cannot undo proven redundancy
        recovery = f"yoke qa requirement list --project {shlex.quote(project)}"
    detail = " Empty -k/-m expressions do not filter tests." if filters else ""
    return (
        "Error: remote selection: redundant_full_suite: the requested paths "
        "cover every declared test root without a test filter; the registered "
        f"full CI gate already owns that verification.{detail} Nothing was "
        f"pushed or dispatched. Use `{recovery}` for the registered gate. "
        "Iterate with `yoke watch pytest --impacted main --bounded` or "
        "`yoke watch pytest -- <test-file-or-node-id>`."
    )

"""Project-local QA method authoring over the registered runner roster."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_one
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.qa_method_definitions import method_metadata_for_runner


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EXECUTOR_CONTRACTS = {
    "worktree_run": {
        "capability": None,
        "verdict_paths": {"automatic"},
    },
    "browser_substrate": {
        "capability": "browser-control",
        "verdict_paths": {"automatic", "agent"},
    },
}


class QaMethodError(ValueError):
    """A project-local method exceeds the registered runner contract."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def register_project_method(
    conn: Any,
    *,
    project: str,
    slug: str,
    name: str,
    description: str,
    runner_id: str,
    verdict_path: str,
    verdict_contract: str,
    evidence_contract: str,
    concurrency_mode: str = "parallel",
    success_policy_params: Optional[dict] = None,
) -> dict:
    """Register a project-owned method without admitting arbitrary runners."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise QaMethodError(f"project {project!r} not found")
    if not _SLUG_RE.fullmatch(slug):
        raise QaMethodError(
            "method slug must contain lowercase words separated by hyphens"
        )
    contract = _EXECUTOR_CONTRACTS.get(runner_id)
    if contract is None:
        raise QaMethodError(
            f"runner {runner_id!r} is not registered for project methods"
        )
    if verdict_path not in contract["verdict_paths"]:
        raise QaMethodError(
            f"runner {runner_id!r} does not support verdict path {verdict_path!r}"
        )
    if concurrency_mode not in {"parallel", "serial"}:
        raise QaMethodError("concurrency_mode must be parallel or serial")
    required = {
        "name": name,
        "description": description,
        "verdict_contract": verdict_contract,
        "evidence_contract": evidence_contract,
    }
    empty = [field for field, value in required.items() if not str(value).strip()]
    if empty:
        raise QaMethodError("project method requires non-empty " + ", ".join(empty))
    method_id = f"project-{identity.slug}-{slug}"
    marker = _p(conn)
    existing = query_one(
        conn,
        f"SELECT project_id FROM qa_methods WHERE id={marker}",
        (method_id,),
    )
    if existing is not None and int(existing["project_id"] or 0) != int(identity.id):
        raise QaMethodError(f"QA method {method_id!r} is already registered")
    stamp = iso8601_now()
    metadata = method_metadata_for_runner(runner_id, verdict_path)
    columns = (
        "id",
        "name",
        "description",
        "source_kind",
        "source_ref",
        "project_id",
        "runner_id",
        "required_capability_kind",
        "verdict_path",
        "verdict_contract",
        "evidence_contract",
        "success_policy_id",
        "success_policy_params",
        "concurrency_mode",
        "display_icon",
        "display_order",
        "display_group",
        "config_contract_id",
        "proof_kind",
        "runner_gloss",
        "created_at",
        "updated_at",
    )
    conn.execute(
        f"INSERT INTO qa_methods ({', '.join(columns)}) "
        f"VALUES ({', '.join([marker] * len(columns))}) "
        "ON CONFLICT(id) DO UPDATE SET "
        "name=EXCLUDED.name, description=EXCLUDED.description, "
        "runner_id=EXCLUDED.runner_id, "
        "required_capability_kind=EXCLUDED.required_capability_kind, "
        "verdict_path=EXCLUDED.verdict_path, "
        "verdict_contract=EXCLUDED.verdict_contract, "
        "evidence_contract=EXCLUDED.evidence_contract, "
        "success_policy_params=EXCLUDED.success_policy_params, "
        "concurrency_mode=EXCLUDED.concurrency_mode, "
        "display_icon=EXCLUDED.display_icon, "
        "display_order=EXCLUDED.display_order, "
        "display_group=EXCLUDED.display_group, "
        "config_contract_id=EXCLUDED.config_contract_id, "
        "proof_kind=EXCLUDED.proof_kind, "
        "runner_gloss=EXCLUDED.runner_gloss, "
        "updated_at=EXCLUDED.updated_at",
        (
            method_id,
            name.strip(),
            description.strip(),
            "project",
            identity.slug,
            int(identity.id),
            runner_id,
            contract["capability"],
            verdict_path,
            verdict_contract.strip(),
            evidence_contract.strip(),
            "all-pass",
            json.dumps(success_policy_params or {}, sort_keys=True),
            concurrency_mode,
            metadata["display_icon"],
            metadata["display_order"],
            metadata["display_group"],
            metadata["config_contract_id"],
            metadata["proof_kind"],
            metadata["runner_gloss"],
            stamp,
            stamp,
        ),
    )
    conn.commit()
    return {
        "id": method_id,
        "project": identity.slug,
        "project_id": int(identity.id),
        "runner_id": runner_id,
        "verdict_path": verdict_path,
    }


__all__ = [
    "QaMethodError",
    "register_project_method",
]

"""Projectable QA method definitions owned by the Machine QA Pack."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.pack_catalog import load_pack_descriptor, packs_root
from yoke_core.domain.qa_catalog_schema import ensure_qa_method_metadata_columns
from yoke_core.domain.qa_method_capabilities import capability_kinds


MACHINE_QA_PACK = "machine-qa"
_METHOD_KEYS = frozenset(
    {
        "id",
        "name",
        "description",
        "runner_id",
        "required_capability_kinds",
        "verdict_path",
        "verdict_contract",
        "evidence_contract",
        "concurrency_mode",
    }
)
_METHOD_METADATA_KEYS = frozenset(
    {
        "display_icon",
        "display_order",
        "display_group",
        "config_contract_id",
        "proof_kind",
        "runner_gloss",
    }
)
_METHOD_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


class MachineQaPackError(ValueError):
    """The Pack's method-definition contract is invalid."""


def _definition_path(
    descriptor: Mapping[str, Any],
    version: str,
) -> Path:
    record = descriptor["versions"][version]
    relative = record.get("qa_methods")
    if not isinstance(relative, str) or not relative:
        raise MachineQaPackError(
            f"{MACHINE_QA_PACK} {version} does not declare qa_methods"
        )
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise MachineQaPackError("machine-qa qa_methods path is unsafe")
    root = packs_root() / MACHINE_QA_PACK / str(record["source"])
    path = root / candidate
    file_sources = {
        str(row["source"]) for row in record.get("files", []) if isinstance(row, dict)
    }
    if relative not in file_sources or not path.is_file():
        raise MachineQaPackError(
            "machine-qa qa_methods must name an inventoried Pack source file"
        )
    return path


def _method(raw: Any) -> dict[str, Any]:
    expected_keys = _METHOD_KEYS | _METHOD_METADATA_KEYS
    if not isinstance(raw, dict) or set(raw) != expected_keys:
        raise MachineQaPackError(
            "machine-qa methods require the complete registered contract"
        )
    row: dict[str, Any] = {
        key: str(raw[key] or "").strip()
        for key in _METHOD_KEYS - {"required_capability_kinds"}
    }
    row["required_capability_kinds"] = list(
        capability_kinds(
            raw["required_capability_kinds"],
            subject=f"machine-qa method {row['id']!r}",
        )
    )
    if not _METHOD_ID.fullmatch(row["id"]):
        raise MachineQaPackError("machine-qa method id is invalid")
    for key in (
        "name",
        "description",
        "verdict_contract",
        "evidence_contract",
    ):
        if not row[key]:
            raise MachineQaPackError(f"machine-qa method {row['id']} lacks {key}")
    if row["runner_id"] not in {"host_control", "agent_mission"}:
        raise MachineQaPackError(
            f"machine-qa method {row['id']} has an invalid runner"
        )
    if "test-machine" not in row["required_capability_kinds"]:
        raise MachineQaPackError(
            f"machine-qa method {row['id']} must require test-machine"
        )
    if row["verdict_path"] not in {"automatic", "agent"}:
        raise MachineQaPackError(
            f"machine-qa method {row['id']} has invalid verdict_path"
        )
    if row["concurrency_mode"] != "serial":
        raise MachineQaPackError(f"machine-qa method {row['id']} must be serial")
    row.update(
        {
            key: str(raw[key] or "").strip()
            for key in _METHOD_METADATA_KEYS - {"display_order"}
        }
    )
    display_order = raw["display_order"]
    if isinstance(display_order, bool) or not isinstance(display_order, int):
        raise MachineQaPackError(
            f"machine-qa method {row['id']} display_order must be an integer"
        )
    row["display_order"] = display_order
    if row["runner_id"] == "agent_mission" and (
        row["required_capability_kinds"] != ["browser-control", "test-machine"]
        or row["verdict_path"] != "agent"
        or row["config_contract_id"] != "agent-mission"
    ):
        raise MachineQaPackError(
            f"machine-qa mission {row['id']} requires both substrates and agent review"
        )
    return row


def load_machine_qa_methods(
    *,
    version: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Load and validate method contracts from the immutable Pack source."""
    descriptor = load_pack_descriptor(MACHINE_QA_PACK)
    selected = version or str(descriptor["latest_version"])
    if selected not in descriptor["versions"]:
        raise MachineQaPackError(f"unknown machine-qa version {selected!r}")
    path = _definition_path(descriptor, selected)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MachineQaPackError(
            "machine-qa method definitions are unreadable"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != 3:
        raise MachineQaPackError("machine-qa method definitions require schema 3")
    methods = payload.get("methods")
    if not isinstance(methods, list) or not methods:
        raise MachineQaPackError("machine-qa method definitions are empty")
    rows = [_method(raw) for raw in methods]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise MachineQaPackError("machine-qa method ids must be unique")
    return selected, rows


def sync_machine_qa_pack_methods(
    conn: Any,
    *,
    commit: bool = True,
) -> list[dict[str, Any]]:
    """Project Pack methods, committing unless the caller owns the transaction."""
    _, methods = load_machine_qa_methods()
    ensure_qa_method_metadata_columns(conn)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    now = iso8601_now()
    columns = (
        "id",
        "name",
        "description",
        "source_kind",
        "source_ref",
        "project_id",
        "runner_id",
        "required_capability_kinds",
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
    assignments = ", ".join(
        f"{column}=EXCLUDED.{column}"
        for column in columns
        if column not in {"id", "created_at"}
    )
    sql = (
        f"INSERT INTO qa_methods({', '.join(columns)}) "
        f"VALUES({', '.join([marker] * len(columns))}) "
        f"ON CONFLICT(id) DO UPDATE SET {assignments}"
    )
    for method in methods:
        conn.execute(
            sql,
            (
                method["id"],
                method["name"],
                method["description"],
                "pack",
                MACHINE_QA_PACK,
                None,
                method["runner_id"],
                json.dumps(method["required_capability_kinds"], sort_keys=True),
                method["verdict_path"],
                method["verdict_contract"],
                method["evidence_contract"],
                "all-pass",
                "{}",
                method["concurrency_mode"],
                method["display_icon"],
                method["display_order"],
                method["display_group"],
                method["config_contract_id"],
                method["proof_kind"],
                method["runner_gloss"],
                now,
                now,
            ),
        )
    if commit:
        conn.commit()
    return methods


__all__ = [
    "MACHINE_QA_PACK",
    "MachineQaPackError",
    "load_machine_qa_methods",
    "sync_machine_qa_pack_methods",
]

"""Validate a complete published model catalog before it becomes visible."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from yoke_contracts.model_reference import lookup_stem, validate_model_record
from yoke_contracts.model_reference_records import ModelRecord, ModelReferenceError


def _date(value: str | None, field: str) -> None:
    if not value:
        raise ModelReferenceError("source_missing", f"{field} is required")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ModelReferenceError(
            "source_invalid", f"{field} must be an ISO date"
        ) from exc


def validate_catalog(payload: object) -> tuple[ModelRecord, ...]:
    """Validate records and every key through which a launch can find one."""
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise ModelReferenceError(
            "catalog_invalid", "catalog must be a list of records"
        )
    if not payload:
        raise ModelReferenceError("catalog_empty", "catalog needs at least one record")
    records: list[ModelRecord] = []
    owners: dict[str, str] = {}
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise ModelReferenceError(
                "catalog_invalid", "each catalog entry must be an object"
            )
        record = validate_model_record(raw)
        if not record.source_urls:
            raise ModelReferenceError(
                "source_missing", f"{record.model_id} needs source_urls"
            )
        _date(record.checked_at, f"{record.model_id}.checked_at")
        if record.api_price is not None:
            if not record.api_price.source_url:
                raise ModelReferenceError(
                    "source_missing", f"{record.model_id}.api_price needs source_url"
                )
            _date(
                record.api_price.checked_at, f"{record.model_id}.api_price.checked_at"
            )
        for key in (record.model_id, *record.aliases):
            for selector in (key, lookup_stem(key)):
                previous = owners.get(selector)
                if previous and previous != record.model_id:
                    raise ModelReferenceError(
                        "alias_collision",
                        f"{selector} names both {previous} and {record.model_id}",
                    )
                owners[selector] = record.model_id
        if record.model_id in (existing.model_id for existing in records):
            raise ModelReferenceError(
                "model_duplicate", f"{record.model_id} appears more than once"
            )
        records.append(record)
    return tuple(records)


def catalog_diff(
    current: Sequence[ModelRecord], candidate: Sequence[ModelRecord]
) -> dict[str, Any]:
    """Return a stable review summary for one complete replacement."""
    before = {record.model_id: record.to_dict() for record in current}
    after = {record.model_id: record.to_dict() for record in candidate}
    changed_ids = sorted(
        key for key in before.keys() & after.keys() if before[key] != after[key]
    )
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": changed_ids,
        "added_records": {
            key: after[key] for key in sorted(after.keys() - before.keys())
        },
        "removed_records": {
            key: before[key] for key in sorted(before.keys() - after.keys())
        },
        "changes": {
            key: {
                field: {
                    "before": before[key].get(field),
                    "after": after[key].get(field),
                }
                for field in sorted(before[key].keys() | after[key].keys())
                if before[key].get(field) != after[key].get(field)
            }
            for key in changed_ids
        },
        "unchanged_count": sum(
            1 for key in before.keys() & after.keys() if before[key] == after[key]
        ),
    }


__all__ = ["catalog_diff", "validate_catalog"]

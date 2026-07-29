"""Shared fixture identity for QA plan execution tests."""

import hashlib
import json

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"
TEST_EXECUTION_TARGET = {
    "environment": {"name": "development"},
    "endpoints": {"app_url": "", "api_url": ""},
}


def synthetic_execution_target(
    *,
    project_id: int,
    project: str,
) -> tuple[dict, str]:
    """Return one internally coherent target and its canonical digest."""
    target = {
        "schema": 1,
        "tenant": {"id": 1, "slug": "test-org", "name": "Test org"},
        "project": {
            "id": int(project_id),
            "slug": str(project),
            "name": str(project),
        },
        "site": {"id": "test-site"},
        "environment": {"id": "test-env", "name": "development"},
        "endpoints": {},
    }
    encoded = json.dumps(target, sort_keys=True, separators=(",", ":")).encode()
    return target, hashlib.sha256(encoded).hexdigest()


__all__ = [
    "TEST_EXECUTION_TARGET",
    "TEST_ITEM_ID",
    "TEST_ITEM_REF",
    "synthetic_execution_target",
]

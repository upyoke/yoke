"""Atomic, item-owned reservations of the one permitted flaky train retry."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.item_json_sections import upsert_json_section
from yoke_core.domain.db_savepoint import SavepointLostError, savepoint
from yoke_core.domain.merge_queue_flake_retry import RETRY_EXHAUSTED, RETRY_SECTION


class ClaimRetryRequest(BaseModel):
    pr_number: str = Field(min_length=1)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    run_url: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


class ClaimRetryResponse(BaseModel):
    claimed: bool


def _error(code, message):
    return HandlerOutcome(
        primary_success=False, error=FunctionError(code=code, message=message)
    )


def reserve_retry(conn, item_id, body, session_id):
    """Lock the item, including the initially absent section; caller commits."""
    postgres = db_backend.connection_is_postgres(conn)
    p, lock = ("%s", " FOR UPDATE") if postgres else ("?", "")
    item = conn.execute(
        f"SELECT id FROM items WHERE id={p}{lock}", (item_id,)
    ).fetchone()
    if item is None:
        raise ValueError("target_not_found: restore the item's durable record")
    row = conn.execute(
        f"SELECT content FROM item_sections WHERE item_id={p} AND section_name={p}",
        (item_id, RETRY_SECTION),
    ).fetchone()
    # A corrupt receipt is a refusal, never an empty budget.
    history = json.loads(row[0]) if row else {"retries": []}
    retries = history["retries"]
    identity = (body.pr_number, body.head_sha, body.base_sha)
    if any(
        (entry["pr_number"], entry["head_sha"], entry["base_sha"]) == identity
        for entry in retries
    ):
        return False
    retries.append({
        **body.model_dump(), "session_id": session_id,
        "recorded_at": format_instant(utc_now()),
    })
    with savepoint(conn, "merge_train_retry", owns=False):
        upsert_json_section(
            conn, item_id=item_id, section=RETRY_SECTION, payload=history, ordering=210
        )
    return True


def handle_claim_retry(request):
    try:
        body = ClaimRetryRequest.model_validate(request.payload)
        if not body.reason.strip() or not body.run_url.startswith("https://"):
            return _error(
                "payload_invalid", "Name the failed test, flake reason and HTTPS CI run URL."
            )
        if request.target.item_id is None:
            return _error("target_invalid", "Retry requires the item's public reference.")
        with db_helpers.connect() as conn:
            claimed = reserve_retry(
                conn, int(request.target.item_id), body, request.actor.session_id
            )
            conn.commit()
    except ValidationError as exc:
        return _error("payload_invalid", f"Correct the retry claim fields: {exc}")
    except SavepointLostError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed on unreadable history
        return _error(
            "merge_train_flake_retry_unrecorded",
            f"{exc}; restore the item's {RETRY_SECTION} record and retry; nothing was armed.",
        )
    if not claimed:
        return _error(
            RETRY_EXHAUSTED,
            "A retry is already recorded for this pull request and head/base. "
            "A second failure belongs to this item: inspect the failed run, "
            "correct the actual cause and re-verify before re-entering the queue. "
            "Do not use empty commits to reset the budget.",
        )
    return HandlerOutcome(primary_success=True, result_payload={"claimed": True})

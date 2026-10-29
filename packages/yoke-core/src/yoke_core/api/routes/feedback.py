"""Tokenless, shape-checked public feedback intake."""

import logging
import re
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from yoke_contracts.release_version import release_version
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.ouroboros_entry_insert import cmd_insert_entry
from yoke_core.domain.actors import seed_system_actor
from yoke_core.api.main_db import get_db_readwrite

router = APIRouter()
_log = logging.getLogger(__name__)
RECEIVING_PROJECT = "yoke"
SERVICE_COMPONENT = "feedback"


class PublicFeedback(BaseModel):
    category: Literal["failed", "new", "unclear", "observation", "idea"]
    evidence: str = Field(min_length=1, max_length=4000)
    yoke_version: str | None = None
    universe_fingerprint: str | None = None
    reporter_email: str | None = None
    agent: str = "unknown"

    @field_validator("evidence")
    @classmethod
    def evidence_present(cls, value):
        if not value.strip():
            raise ValueError("evidence must not be blank")
        return value

    @field_validator("yoke_version")
    @classmethod
    def version_shape(cls, value):
        if value:
            release_version(value)
        return value

    @field_validator("universe_fingerprint")
    @classmethod
    def fingerprint_shape(cls, value):
        if value:
            slug, separator, timestamp = value.partition("@")
            if not separator or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
                raise ValueError("fingerprint must be slug@timestamp")
            parse_instant(timestamp)
        return value


def store_feedback(note):
    with get_db_readwrite() as conn:
        # Resolve the receiving project before establishing the service identity.
        from yoke_core.domain.project_identity import resolve_project_id
        resolve_project_id(conn, RECEIVING_PROJECT)
        actor = seed_system_actor(conn, SERVICE_COMPONENT)
        return cmd_insert_entry(conn, utc_now(), note.agent, None, note.category,
            note.evidence, project=RECEIVING_PROJECT, actor_id=actor, session_id="",
            reporter_email=note.reporter_email, yoke_version=note.yoke_version,
            universe_fingerprint=note.universe_fingerprint)


@router.post("/feedback")
async def receive_feedback(request: Request):
    try:
        if not request.headers.get("user-agent", "").startswith("yoke-cli/"):
            raise ValueError("User-Agent must start with yoke-cli/")
        note = PublicFeedback.model_validate(await request.json())
    except Exception:
        return JSONResponse(status_code=400, content={"error": "feedback_shape_invalid"})
    try:
        entry = await run_in_threadpool(store_feedback, note)
    except Exception as exc:
        _log.error("feedback_store_unavailable: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"error": "feedback_store_unavailable",
            "recovery": "Restore the receiving database and feedback project, then retry the same evidence."})
    return JSONResponse(status_code=201, content={"entry_id": entry})

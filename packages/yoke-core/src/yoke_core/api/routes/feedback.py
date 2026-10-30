"""Tokenless, shape-checked public feedback intake."""

import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from yoke_contracts.feedback_provenance import (
    validate_feedback_identity, FeedbackIdentityError, UPGRADE_RECOVERY,
)
from yoke_contracts.release_version import reporting_version_shape
from yoke_contracts.timestamps import utc_now
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
    yoke_version: str
    universe_fingerprint: str
    reporter_email: str | None = None
    agent: str

    @field_validator("evidence")
    @classmethod
    def evidence_present(cls, value):
        if not value.strip():
            raise ValueError("evidence must not be blank")
        return value


def store_feedback(note):
    with get_db_readwrite() as conn:
        # Resolve the receiving project before establishing the service identity.
        from yoke_core.domain.project_identity import resolve_project_id
        resolve_project_id(conn, RECEIVING_PROJECT)
        actor = seed_system_actor(conn, SERVICE_COMPONENT)
        return cmd_insert_entry(conn, utc_now(), note.agent, note.category,
            note.evidence, project=RECEIVING_PROJECT, actor_id=actor, session_id="",
            reporter_email=note.reporter_email, yoke_version=note.yoke_version,
            universe_fingerprint=note.universe_fingerprint)


@router.post("/feedback")
async def receive_feedback(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("expected object")
        validate_feedback_identity(yoke_version=body.get("yoke_version"),
                                   universe_fingerprint=body.get("universe_fingerprint"),
                                   agent=body.get("agent"))
    except FeedbackIdentityError as exc:
        return JSONResponse(status_code=400, content={"error": exc.code, "recovery": exc.recovery})
    except Exception:
        return JSONResponse(status_code=400, content={"error": "feedback_shape_invalid",
            "recovery": "Provide a feedback category and 1 to 4000 characters of evidence."})
    user_agent = request.headers.get("user-agent", "")
    try:
        if not user_agent.startswith("yoke-cli/"):
            raise ValueError("missing CLI identity")
        version = reporting_version_shape(user_agent[len("yoke-cli/"):])
        if version != body["yoke_version"]:
            raise ValueError("CLI identity differs from payload")
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "feedback_user_agent_invalid",
            "recovery": UPGRADE_RECOVERY})
    try:
        note = PublicFeedback.model_validate(body)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "feedback_shape_invalid",
            "recovery": "Provide a feedback category and 1 to 4000 characters of evidence."})
    try:
        entry = await run_in_threadpool(store_feedback, note)
    except Exception as exc:
        _log.error("feedback_store_unavailable: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"error": "feedback_store_unavailable",
            "recovery": "Restore the receiving database and feedback project, then retry the same evidence."})
    return JSONResponse(status_code=201, content={"entry_id": entry})

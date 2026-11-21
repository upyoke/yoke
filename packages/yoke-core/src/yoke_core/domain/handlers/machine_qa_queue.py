"""Registered steering commands for Test Machine queue turns."""

from functools import partial

from pydantic import BaseModel, Field, ValidationError
from psycopg.errors import LockNotAvailable, QueryCanceled

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.auth_context import StandardAuthContext
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.events import emit_event
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.qa_host_queue import lock_host_queue
from yoke_core.domain.qa_host_queue_steering import (
    QueueEditRefused,
    hand_over,
    place_waiter,
)
from yoke_core.domain.qa_plan_execution_stop import execution_project_id
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.session_steering_authority import require_operator_seat
from yoke_core.domain.sessions_analytics_core import SessionError


class QueueEdit(BaseModel):
    host: str = Field(min_length=1, pattern=r"\S")
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class PlaceRequest(QueueEdit):
    execution: str = Field(min_length=1)
    position: int = Field(ge=1)


class HandOverRequest(QueueEdit):
    from_execution: str = Field(min_length=1)
    to_execution: str = Field(min_length=1)


class QueueEditResult(BaseModel):
    execution_id: str
    host: str
    position: int | None
    prior_execution_id: str | None = None


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False, error=FunctionError(code=code, message=message)
    )


def _edit(request, *, model, event_name):
    try:
        body = model.model_validate(request.payload)
    except ValidationError as exc:
        return _failure("payload_invalid", f"{exc}; see yoke test-machine queue --help")
    if not request.target.project_id or not str(request.actor.actor_id or "").isdigit():
        return _failure(
            "qa_host_queue_actor_required",
            "Run from a registered steering session in the execution's project, or pass --project P.",
        )
    placing = isinstance(body, PlaceRequest)
    ids = [body.execution] if placing else [body.from_execution, body.to_execution]
    with connect() as conn:
        try:
            project = resolve_project_id(conn, str(request.target.project_id))
            # Verify the caller's seat before taking any execution or queue lock.
            require_operator_seat(
                conn,
                caller_session_id=request.actor.session_id,
                project_id=project,
                action="Edit the Test Machine queue",
            )
            executions = {
                execution_id: lock_plan_execution(conn, execution_id)
                for execution_id in sorted(set(ids))
            }
            projects = {
                key: execution_project_id(conn, row) for key, row in executions.items()
            }
            if projects[ids[0]] != project:
                raise ValueError(
                    "The first execution belongs to another project; pass its --project P and retry"
                )
            for other in sorted(set(projects.values()) - {project}):
                require_operator_seat(
                    conn,
                    caller_session_id=request.actor.session_id,
                    project_id=other,
                    action="Hand over a Test Machine turn",
                )
            lock_host_queue(conn)
            if placing:
                result = place_waiter(
                    conn, executions[ids[0]], body.host, body.position
                )
            else:
                result = hand_over(
                    conn, executions[ids[0]], executions[ids[1]], body.host
                )
            emit_event(
                event_name,
                event_kind="system",
                event_type="lease_lifecycle",
                source_type="backend",
                session_id=request.actor.session_id,
                auth_context=StandardAuthContext(actor_id=int(request.actor.actor_id)),
                project=str(project),
                context={**result, "reason": body.reason},
                conn=conn,
                transactional=True,
            )
            conn.commit()
        except SessionError as exc:
            conn.rollback()
            return _failure(exc.code, exc.message)
        except QueueEditRefused as exc:
            conn.rollback()
            return _failure(exc.code, str(exc))
        except (LookupError, ValueError) as exc:
            conn.rollback()
            return _failure(
                "qa_host_queue_edit_refused",
                f"{exc}. Read the current executions in the steering fleet report before retrying.",
            )
        except (LockNotAvailable, QueryCanceled):
            conn.rollback()
            return _failure(
                "qa_host_queue_busy",
                "The QA execution or host queue stayed locked. Inspect the fleet report and retry the queue edit.",
            )
    return HandlerOutcome(primary_success=True, result_payload=result)


def register(registry):
    for action, model, event in (
        ("place", PlaceRequest, "QaHostWaiterPlaced"),
        ("hand_over", HandOverRequest, "QaHostTurnHandedOver"),
    ):
        registry.register(
            f"test_machine.queue.{action}",
            partial(_edit, model=model, event_name=event),
            model,
            QueueEditResult,
            stability="stable",
            minimum_serving_version="next-release",
            owner_module=__name__,
            target_kinds=["global"],
            side_effects=["qa_host_queue_write", "coordination_claim"],
            emitted_event_names=[event],
            guardrails=["steering_seat_required", "serialized_host_queue"],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=True,
        )

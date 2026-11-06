"""Create a release set on one immutable source, compensating refused creates."""

import sys
from copy import copy

from yoke_cli.commands._helpers import build_actor, ensure_handlers_loaded, emit_response
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_cli.transport.response_limits import DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS
from yoke_contracts.api.function_call import TargetRef, FunctionError
from yoke_cli.commands.adapters.deployment_run_create_retry import build_timeout_repeat
from yoke_cli.commands.adapters.deployment_execution_authority import creation_connection_error
from yoke_cli.commands.adapters.deployment_pin_guard import pin_regression_error


def create_release_set(parsed, flows, payload, human_writer):
    ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = TargetRef(kind="global")
    results, made = [], []
    response = None
    for flow in flows:
        member = copy(parsed)
        member.flow = flow
        if refusal := creation_connection_error(
            "create", project=parsed.project, flow=flow, environment=None
        ):
            response = _refused(response, refusal)
            break
        if parsed.retry_of or parsed.project_repo_path:
            if refusal := pin_regression_error(member):
                response = _refused(response, refusal)
                break
        request = {**payload, "flow": flow,
                   "idempotency_key": f"{parsed.idempotency_key}:{flow}"}
        response = call_dispatcher(
            function_id="deployment_runs.create", target=target, payload=request,
            actor=actor, timeout_s=DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS,
        )
        response = build_timeout_repeat(target, request)(response, actor)
        if not response.success:
            break
        result = response.result or {}
        results.append(result)
        if not result.get("replayed"):
            made.append(result["run_id"])
        # The first create's server binds a gate-branch tip when no source was
        # given; every following create receives that exact immutable commit.
        if not payload.get("release_lineage"):
            lineage = result.get("release_lineage")
            if not lineage:
                response = _refused(response,
                    "release_set_source_unbound: the first flow returned no source commit; "
                    "give --project-repo-path and --source-ref and retry with a new key")
                break
            payload = {**payload, "release_lineage": lineage}
    if response is None:
        return 1
    if not response.success:
        for run_id in reversed(made):
            cancelled = call_dispatcher(
                function_id="deployment_runs.terminalize",
                target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
                payload={"disposition": "cancelled",
                         "reason": "release set creation refused; cancelling earlier creates"},
                actor=actor,
            )
            if not cancelled.success:
                print(f"release_set_cleanup_failed: run {run_id}: {cancelled.error}; "
                      f"cancel it with yoke deployment-runs terminalize {run_id} "
                      "--disposition cancelled --reason 'release set creation refused'",
                      file=sys.stderr)
        return emit_response(response, json_mode=parsed.json_mode)
    combined = response.model_copy(update={"result": {"runs": results}})

    def writer(_response, stdout, stderr):
        for result in results:
            human_writer(response.model_copy(update={"result": result}), stdout, stderr)

    return emit_response(combined, json_mode=parsed.json_mode, human_writer=writer)


def _refused(response, message):
    from yoke_contracts.api.function_call import FunctionCallResponse

    if response is None:
        response = FunctionCallResponse(success=False,
            function="deployment_runs.create", version="v1", request_id="release-set")
    return response.model_copy(update={"success": False,
        "error": FunctionError(code="release_set_create_refused", message=message)})

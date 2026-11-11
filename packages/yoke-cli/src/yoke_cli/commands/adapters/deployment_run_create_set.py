"""Create a release set in one call: every flow's run commits, or none does."""

from copy import copy

from yoke_cli.commands._helpers import build_actor, ensure_handlers_loaded, emit_response
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.response_limits import DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands.adapters.deployment_run_create_retry import build_timeout_repeat
from yoke_cli.commands.adapters.deployment_execution_authority import creation_connection_error
from yoke_cli.commands.adapters.deployment_pin_guard import pin_regression_error


def create_release_set(parsed, flows, payload, human_writer):
    """Send every flow in one create; the server binds one source for all.

    A refusal on any flow leaves no run and no takeover, so a repeat with the
    same key creates the whole set.
    """
    import sys

    for flow in flows:
        if refusal := creation_connection_error(
            "create", project=parsed.project, flow=flow, environment=None
        ):
            print(f"error: {refusal}", file=sys.stderr)
            return 2
        if parsed.project_repo_path:
            member = copy(parsed)
            member.flow = flow
            if refusal := pin_regression_error(member):
                print(f"Error: {refusal}", file=sys.stderr)
                return 1
    ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = TargetRef(kind="global")
    request = {**{k: v for k, v in payload.items() if k != "flow"}, "flows": list(flows)}
    response = call_dispatcher(
        function_id="deployment_runs.create", target=target, payload=request,
        actor=actor, timeout_s=DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS,
    )
    response = build_timeout_repeat(target, request)(response, actor)
    if not response.success:
        return emit_response(response, json_mode=parsed.json_mode)
    results = list((response.result or {}).get("runs") or [])

    def writer(_response, stdout, stderr):
        from yoke_cli.commands.adapters.deployment_run_create import write_release_instructions

        # Every run in a set shares one project, so its release policy prints once.
        write_release_instructions(results[0] if results else {}, stdout)
        for result in results:
            human_writer(response.model_copy(update={"result": result}), stdout, stderr)

    return emit_response(response, json_mode=parsed.json_mode, human_writer=writer)

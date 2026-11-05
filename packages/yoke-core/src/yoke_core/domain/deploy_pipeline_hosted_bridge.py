"""Bind the hosted release bridge to the control plane owning the run."""

from __future__ import annotations

from yoke_contracts.api_urls import validate_control_api_url
from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema import (
    active_connection,
    same_universe_https_env,
    TRANSPORT_HTTPS,
)
from yoke_core.domain.hosted_promotion_receipt import HOSTED_BRIDGE_WORKFLOW


def hosted_bridge_inputs(
    workflow: str, values: dict[str, str]
) -> tuple[dict[str, str], str]:
    """Seal the owner endpoint for every bridge dispatch, including retries."""
    if workflow != HOSTED_BRIDGE_WORKFLOW:
        return values, ""
    try:
        config = machine_config.load_config()
        connection = active_connection(config)
        if connection.get("transport") != TRANSPORT_HTTPS:
            sibling = same_universe_https_env(config, connection["env"])
            if not sibling:
                raise ValueError("no paired HTTPS connection")
            connection = active_connection(config, explicit_env=sibling)
        endpoint = validate_control_api_url(connection.get("api_url", ""))
    except (RuntimeError, ValueError, OSError):
        return values, (
            "release_control_endpoint_unavailable: the run's owning connection "
            "needs a credential-free HTTPS api_url. Configure it (or its paired "
            "HTTPS connection for a database-admin driver) with "
            "`yoke connection set <owning-env> --transport https --api-url HTTPS-URL`."
        )
    return {**values, "control_plane_api_url": endpoint}, ""


def start_hosted_consumer_proof(stages, candidate_sha, bound_inputs) -> None:
    """Start the bridge's exact pair before CI; publication still awaits proof."""
    import subprocess
    from yoke_core.domain.platform_consumer_dispatch import dispatch_pair
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    if not any(stage.get("config", {}).get("workflow") == HOSTED_BRIDGE_WORKFLOW
               for stage in stages):
        return
    consumer_sha = str(bound_inputs.get("consumer_sha") or "")
    if not all(len(value) == 40 and all(c in "0123456789abcdef" for c in value)
               for value in (candidate_sha, consumer_sha)):
        print("consumer_proof_start_unavailable: exact pair is absent; "
              "the bridge will require and start proof from its bound inputs")
        return

    def run_yoke(argv, *, timeout):
        args = list(argv[1:])
        index = args.index("--project")
        project = args[index + 1]
        del args[index:index + 2]
        result = _github_actions(*args, project=project, timeout=timeout)
        return result.returncode, result.stdout, result.stderr

    # A later consumer move wastes this early proof but is harmless: the bridge
    # joins only its own bound pair and refuses mismatched evidence.
    try:
        run_id, error = dispatch_pair(run_yoke, candidate_sha, consumer_sha)
    except (OSError, subprocess.SubprocessError) as exc:
        run_id, error = "", str(exc)
    if error:
        print(f"consumer_proof_start_unavailable: {error}; "
              "the bridge will retry this exact pair before publication")
    else:
        print(f"Consumer proof started or joined: run {run_id}; "
              f"product {candidate_sha}, consumer {consumer_sha}; "
              "the bridge will await the verdict")

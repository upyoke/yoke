"""Compatibility imports for the client-safe Machine QA execution contract."""

from yoke_contracts.machine_qa_execution import (
    HOST_CONTROL_PROTOCOL,
    HostControlExecutionContract,
    HostControlOperation,
    MachineQaCaseContract,
    HOST_BASELINES,
    VERIFICATION_CHECKS,
    execution_contract_digest,
    issue_execution_contract,
)


__all__ = [
    "HOST_CONTROL_PROTOCOL",
    "HostControlExecutionContract",
    "HostControlOperation",
    "MachineQaCaseContract",
    "HOST_BASELINES",
    "VERIFICATION_CHECKS",
    "execution_contract_digest",
    "issue_execution_contract",
]


def public_case_snapshots(conn, cases):
    """Compose client identities in the issuing transaction before sealing digests."""
    from yoke_core.domain.function_response_refs import collect_item_ids, public_result
    from yoke_core.domain.item_ref_render import render_item_refs
    from yoke_core.domain.qa_execution_environment_target import target_digest

    snapshots = [dict(case) for case in cases]
    for case in snapshots:
        if "deployment_member_ref" in case:
            case["deployment_member_public_ref"] = case.pop("deployment_member_ref")
    ids = collect_item_ids(snapshots)
    refs = render_item_refs(conn, ids)
    if ids - refs.keys():
        raise ValueError(
            "public_response_identity_unavailable: Machine QA subject has no public "
            "identity; restore its project prefix and item sequence before retrying"
        )
    snapshots = public_result(snapshots, refs)
    for case in snapshots:
        case["execution_target_digest"] = target_digest(case["execution_target"])
    return snapshots

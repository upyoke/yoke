"""Supply real bundle citations in review fixtures."""

import base64

from yoke_core.domain.qa_mission_stop_settlement import NON_PROOF_ARTIFACT_TYPES


def cite_case(bundle, rationale):
    (case,) = bundle["cases"]
    artifacts = case["artifacts"]
    if artifacts:
        product = [
            a for a in artifacts if a.get("artifact_type") not in NON_PROOF_ARTIFACT_TYPES
        ]
        return f"{rationale} See artifact {(product or artifacts)[0]['id']}."
    return f"{rationale} See run {case['capture_run_id']}."


def attach_product_evidence(actor, requirement_id, run_id):
    """Attach what a walked mission saw, so its pass rests on product proof."""
    from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
    from yoke_core.domain.qa_artifact_recording import handle_qa_artifact_add

    outcome = handle_qa_artifact_add(
        FunctionCallRequest(
            function="qa.artifact.add",
            actor=actor,
            target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
            payload={
                "run_id": int(run_id),
                "artifact_type": "evidence",
                "content_type": "text/plain",
                "filename": "walk-observation.txt",
                "content_base64": base64.b64encode(b"product behaved").decode(),
            },
        )
    )
    assert outcome.primary_success, outcome.error
    return int(outcome.result_payload["qa_artifact_id"])

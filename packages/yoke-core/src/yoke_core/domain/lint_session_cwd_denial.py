"""Format claim-authority refusals and their specific recovery guidance."""

from typing import Any, Mapping

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_session_cwd_control_plane import build_scope_mismatch_block
from yoke_core.domain.lint_session_cwd_foreign_lane import (
    FAILURE_CLASS as FOREIGN_LANE_FAILURE_CLASS,
    build_denial_message as build_foreign_lane_message,
)
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)
from yoke_core.domain.lint_session_cwd_repo_command import repo_command_block
from yoke_core.domain.lint_payload_path_use import UNRESOLVED_HOME_PATH
from yoke_core.domain.lint_session_cwd_validate import ValidationVerdict

CLIENT_HOME_AUTHORITY_UNAVAILABLE = "client_home_metadata_missing_or_invalid"


def build_denial_reason(
    outcome: ValidationVerdict,
    payload: Mapping[str, Any],
    *,
    has_targets: bool,
    command: str,
    read_only: bool,
    machine_home: str | None,
) -> tuple[str, str]:
    authority_reason = ""
    if outcome.failure_class == UNRESOLVED_HOME_PATH:
        authority_reason = UNRESOLVED_HOME_PATH
        body = (
            f"BLOCKED: {UNRESOLVED_HOME_PATH}: {outcome.offending_target}. "
            "This home operand cannot be resolved on the executing machine. "
            "Restore the canonical client-home fact in the hook relay, or spell "
            "the executing machine's absolute path (including other-user homes). "
            "An unresolved home is never joined under the claimed lane."
        )
    elif outcome.failure_class == FOREIGN_LANE_FAILURE_CLASS and outcome.occupant:
        body = build_foreign_lane_message(
            offending_target=outcome.offending_target,
            occupant=outcome.occupant,
            payload=payload,
        )
    else:
        body = build_scope_mismatch_block(
            offending_target=outcome.offending_target,
            claims=outcome.claims,
            repo_roots=outcome.repo_roots,
            command=command,
        )
        body += repo_command_block(payload, outcome.claims) if not has_targets else ""
        tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
        if (
            machine_home == ""
            and read_only
            and tool_name.strip()
            and (not command.strip() or match_read_only_signature(command))
        ):
            authority_reason = CLIENT_HOME_AUTHORITY_UNAVAILABLE
            body += (
                "\nAuthority classification: the relayed client machine-home "
                "metadata was missing or invalid, so this read cannot be "
                "classified as ordinary reference material under the client "
                "home. Restore the canonical client-home fact in the hook "
                "relay and retry."
            )
    return attach_check_id(body, check_id="lint-session-cwd"), authority_reason

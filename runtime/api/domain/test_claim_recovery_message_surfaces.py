"""Canonical CLI contracts for actor-facing claim recovery messages."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.lint_claim_ownership_mutations import _spoof_reason
from yoke_core.domain.path_claims_dispatch_help import REGISTER_DESCRIPTION
from yoke_core.domain.path_claims_dispatch_ownership import OwnershipDenial


_CORE = Path(__file__).parents[3] / "packages" / "yoke-core" / "src" / "yoke_core"
_ATLAS = Path(__file__).parents[3] / "docs" / "atlas.md"
_ACTIVE_RECOVERY_SURFACES = (
    "domain/attestation_rehearsal_dryrun.py",
    "domain/backlog_update_op.py",
    "domain/db_error_hook_query_failure.py",
    "domain/db_claim_prose_check.py",
    "domain/lint_no_agent_runtime_api_import_from_c.py",
    "domain/path_claim_required_gate.py",
    "domain/path_claim_spec_coverage_gate.py",
    "domain/path_claims_dispatch_ownership.py",
    "domain/sessions_resume_block.py",
    "domain/update_status_helpers.py",
    "domain/yoke_function_dispatch_claims.py",
    "domain/handlers/strategy_docs_claims.py",
    "engines/doctor_hc_routed_ownership.py",
    "engines/doctor_hc_work_claim_status_mismatch.py",
)
_LOWER_LEVEL_RECIPES = (
    "python3 -m yoke_core.api.service_client claim-work",
    "python3 -m yoke_core.api.service_client release-work-claim",
    "python3 -m yoke_core.api.service_client db-claim-amend",
    "python3 -m yoke_core.api.service_client path-claim-register",
    "python3 -m yoke_core.api.service_client path-claim-widen",
    "service_client claim-release",
    "yoke_core.hooks.sessions_cli who-claims",
)


def test_actor_facing_recovery_surfaces_do_not_teach_lower_level_clients() -> None:
    for relative_path in _ACTIVE_RECOVERY_SURFACES:
        text = (_CORE / relative_path).read_text()
        for recipe in _LOWER_LEVEL_RECIPES:
            assert recipe not in text, f"{relative_path} teaches {recipe!r}"
        for placeholder in ("--reason <", "--paths <"):
            assert placeholder not in text, (
                f"{relative_path} teaches shell-unsafe {placeholder!r}"
            )


def test_path_ownership_denial_uses_public_acquire_and_holder_reads() -> None:
    denial = OwnershipDenial(
        action="widen",
        item_id=81,
        claim_id=9,
        caller_session_id="caller",
        holder_session_id="holder",
    )

    safe_recipe = 'yoke claims work acquire --item YOK-81 --reason "<intent>"'
    assert safe_recipe in denial.message
    assert "--reason <intent>" not in denial.message
    assert "yoke claims work holder-get YOK-81" in denial.message
    assert denial.context()["recovery"].startswith("yoke claims work acquire")
    assert "service_client" not in denial.message


def test_operator_break_glass_guidance_does_not_embed_a_private_recipe() -> None:
    reason = _spoof_reason("service-client/claim-work", "foreign-session")

    assert "operator break-glass release surface named in the Atlas" in reason
    assert "service_client claim-release" not in reason


def test_operator_break_glass_recipe_is_present_in_atlas() -> None:
    text = _ATLAS.read_text(encoding="utf-8")
    assert "### Human-only stranded work-claim release" in text
    assert "service_client claim-release" in text
    assert "--claim-id CLAIM_ID" in text


def test_exception_help_uses_the_public_register_mode() -> None:
    assert "Exception mode (canonical no-claim justification" in REGISTER_DESCRIPTION
    assert "yoke claims path register" in REGISTER_DESCRIPTION
    assert "--mode exception" in REGISTER_DESCRIPTION
    assert "--exception-reason" in REGISTER_DESCRIPTION

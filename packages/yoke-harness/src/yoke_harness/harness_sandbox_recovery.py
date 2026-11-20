"""Recovery for an OS permission denial in the active harness."""

from yoke_contracts.harness_family_identity import family_env_session_id
from yoke_contracts.harness_sandbox_recovery import running_harness_family
from yoke_contracts.harness_unattended_posture import (
    CODEX_FAMILY,
    CURSOR_FAMILY,
    POSTURE_RECOVERY,
    codex_posture_problems,
)
from yoke_harness.codex_session_posture import (
    codex_posture_recovery,
    read_codex_session_posture,
)


def sandbox_recovery() -> str | None:
    family = running_harness_family()
    if family == CODEX_FAMILY:
        session_id = family_env_session_id(CODEX_FAMILY)
        facts, _reason = read_codex_session_posture(session_id) if session_id else (None, "")
        if facts is not None and not codex_posture_problems(facts):
            return None
        return (
            "A Codex session can restrict Yoke's access to the control plane. "
            + codex_posture_recovery()
        )
    if family == CURSOR_FAMILY:
        return f"The Cursor sandbox can block Yoke's control plane. {POSTURE_RECOVERY}"
    return None

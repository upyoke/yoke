"""Judge active session permission evidence, separately from machine config."""

from yoke_contracts.harness_unattended_posture import (
    POSTURE_RECOVERY,
    codex_posture_problems,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_harness.codex_session_posture import read_codex_session_posture
from yoke_harness.hooks.session_permission_mode import read_permission_mode
from yoke_core.engines.doctor_hc_harness_unattended_posture import (
    inspect_unattended_posture,
)


def session_posture(
    harness_id: str, surface_id: str | None, *, session_id: str
) -> tuple[str, str]:
    if (harness_id, surface_id) in (
        ("codex", "codex-vscode"),
        ("cursor", "cursor-desktop"),
    ):
        confirm = (
            "Confirm Cursor Settings → Agents → Run Everything is on"
            if harness_id == "cursor"
            else "Confirm Full Access is selected in this Codex VS Code chat"
        )
        return "WARN", f"HARNESS_POSTURE_CONFIRM_REQUIRED: {confirm}."
    if harness_id == "codex" and surface_id in ("codex-cli", "codex-desktop"):
        facts, reason = read_codex_session_posture(session_id)
        if facts is None:
            return "FAIL", compose_refusal(
                f"HARNESS_POSTURE_UNVERIFIED: {reason}",
                recovery="rerun in a new turn after it is saved; if it persists, start a new chat and rerun `yoke doctor run --session`",
            )
        problems = codex_posture_problems(facts)
        if problems:
            return "FAIL", compose_refusal(
                "HARNESS_POSTURE_RESTRICTED: " + "; ".join(problems),
                recovery="select Full Access in this chat's permissions control, then rerun `yoke doctor run --session` in a new turn; if organization policy prevents Full Access, ask your administrator",
            )
        return (
            "PASS",
            f"{surface_id} records never and danger-full-access for this turn.",
        )
    if harness_id == "claude-code" and surface_id in (
        "claude-cli",
        "claude-desktop",
        "claude-vscode",
    ):
        facts = read_permission_mode(session_id)
        if facts is None:
            return "FAIL", compose_refusal(
                "HARNESS_POSTURE_UNVERIFIED: no readable hook-reported permission mode",
                recovery="send any prompt in this chat, then rerun `yoke doctor run --session`",
            )
        if facts["permission_mode"] != "bypassPermissions":
            return "FAIL", compose_refusal(
                "HARNESS_POSTURE_RESTRICTED: this session is not in bypassPermissions mode",
                recovery="select bypass permissions in this chat, send any prompt, then rerun `yoke doctor run --session`",
            )
        return "PASS", f"{surface_id} records bypassPermissions for this session."
    if harness_id == "cursor" and surface_id == "cursor-cli":
        verdict, detail = inspect_unattended_posture(harness_id, installed=True)
        if verdict == "PASS":
            return verdict, "cursor-cli runs yoke unattended."
        code = (
            "HARNESS_POSTURE_UNVERIFIED"
            if detail.startswith("HARNESS_POSTURE_UNVERIFIED")
            else "HARNESS_POSTURE_RESTRICTED"
        )
        return "FAIL", compose_refusal(
            detail if code in detail else f"{code}: {detail}",
            recovery=f"{POSTURE_RECOVERY} Then start a new session",
        )
    return "FAIL", compose_refusal(
        "HARNESS_POSTURE_UNVERIFIED: this session has an unknown harness surface",
        recovery="restore hook registration from a supported harness surface, then rerun `yoke doctor run --session`",
    )

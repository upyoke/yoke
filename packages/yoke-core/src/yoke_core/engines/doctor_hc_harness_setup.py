"""Doctor's machine-local, shared harness-setup check and repair."""

from yoke_contracts.harness_machine_hooks import installed_machine_hooks
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_harness.harness_setup_reconcile import (
    inspect_harness_setup,
    reconcile_harness_setup,
)
from yoke_harness.session_relay_harness_reconcile import (
    read_reconcile_state,
    remember_reconcile_result,
)
from yoke_harness.session_relay_surface_probes import (
    APP_SURFACE_PROBES,
    resolve_native_cli,
)

SLUG = "harness-setup"
TITLE = "Every registered checkout and lane is set up in every installed harness"
RECOVERY = "Run `yoke doctor run --only harness-setup --fix`."


def codex_home_without_codex() -> str:
    spec = next((s for s in installed_machine_hooks() if s.harness_id == "codex"), None)
    if (
        spec
        and not resolve_native_cli("codex")
        and not APP_SURFACE_PROBES["codex-desktop"].exists()
    ):
        return (
            f"codex_home_without_codex: {spec.home_path()}. If you never installed "
            f"Codex, remove {spec.home_path()}; otherwise open Codex once."
        )
    return ""


def hc_harness_setup(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    result = reconcile_harness_setup() if args.fix else inspect_harness_setup()
    problems = [
        row.line() for row in result.rows if row.outcome in ("refused", "failed")
    ]
    if args.fix:
        try:
            remember_reconcile_result(result)
        except OSError as exc:
            problems.append(
                f"harness_reconcile_state_unwritable: {exc}; repair relay state permissions."
            )
    orphan = codex_home_without_codex()
    if orphan:
        problems.append(orphan)
    state = read_reconcile_state()
    if state.get("failure"):
        problems.append(f"relay_last_reconcile_failed: {state['failure']}")
    if problems:
        rec.record(SLUG, TITLE, "FAIL", "\n".join([*problems, RECOVERY]))
        return
    harnesses = [s.harness_id for s in installed_machine_hooks()]
    targets = {
        r.target_path
        for r in result.rows
        if r.facet == "folder_trust" and r.outcome != "skipped_not_installed"
    }
    rec.record(
        SLUG,
        TITLE,
        "PASS" if harnesses else "N/A",
        f"{', '.join(harnesses)}; {len(targets)} targets"
        if harnesses
        else "No harness home is installed; no files were created.",
    )

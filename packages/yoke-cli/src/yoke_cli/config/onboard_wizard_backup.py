"""Account-step backup validation, restore consent, and continuation."""

from __future__ import annotations

from yoke_cli.config import onboard_backup as backup
from yoke_cli.config.onboard_wizard_state import _View
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.setup_prompt import TONE_ERROR, TONE_OK, SelectionRow, SetupPrompt

START_ROWS = [
    SelectionRow("fresh", "Start fresh", "create a new universe"),
    SelectionRow("backup", "Start from a backup", "bring your account and projects"),
    SelectionRow("back", "Back", "choose another Yoke home"),
]


def choose_server_start(shell, setup, fresh) -> None:
    from yoke_cli.config import onboard_wizard_admin_name as admin_name

    if setup.bundle_created:
        fresh()
        return

    def selected(choice):
        if choice == "fresh":
            admin_name.ask_for_server(shell, setup, fresh)
        elif choice == "backup":
            prompt(shell, setup=setup)
        else:
            shell._return_to_destination_picker()

    shell._goto(
        _View(
            SetupPrompt(
                key="connect.server_start",
                step=STEP_CONNECT,
                title="How should this server start?",
                subtitle="A backup carries your account, projects, items, and "
                "strategy docs.",
                choices=tuple(START_ROWS),
            ),
            selected,
        )
    )


def prompt(shell, *, setup=None) -> None:
    shell._goto_input(
        "connect.backup_path",
        STEP_CONNECT,
        "Where is your backup?",
        "Use the portable .tar from uninstall with backup or the web export panel.",
        placeholder="~/Downloads/yoke-backup.tar",
        allow_placeholder=False,
        on_done=lambda value: _validate(shell, value, setup),
    )


def _validate(shell, value, setup) -> None:
    shell._run_checking(
        step=STEP_CONNECT,
        title="Validating your backup.",
        message="Checking the archive, checksum receipt, and database catalog.",
        work=lambda: backup.validate(shell.result.config_path, value),
        on_success=lambda report: _confirm(shell, report, setup),
        on_error=lambda exc: _failure(shell, exc, lambda: prompt(shell, setup=setup)),
        group="onboard-backup-validation",
    )


def _confirm(shell, report, setup) -> None:
    shell._backup_validation = report
    archive = str(report["archive"])
    target = (
        str(setup.directory) if setup is not None else "this machine's local universe"
    )
    shell._goto(
        _View(
            SetupPrompt(
                key="connect.backup_confirm",
                step=STEP_CONNECT,
                title="Start from this backup?",
                message="Apply restores the account before project setup. No name "
                "is needed.",
                detail_lines=(
                    f"Backup: {archive}",
                    f"Account: {report['receipt']['org']}",
                    f"Destination: {target}",
                    "Apply replaces the destination database and revokes imported credentials.",
                    "Your projects, items, and strategy docs come with the backup.",
                ),
                choices=(
                    SelectionRow("apply", "Apply", "restore, then choose a project"),
                    SelectionRow("back", "Back", "choose a different backup"),
                ),
                tone=TONE_OK,
                guidance="Confirm with the person before restoring; it replaces "
                "the destination database.",
            ),
            lambda choice: (
                _apply(shell, archive, setup)
                if choice == "apply"
                else prompt(shell, setup=setup)
            ),
        )
    )


def _apply(shell, archive, setup) -> None:
    def restore():
        imported = (
            bool(setup.raw_token)
            if setup
            else "owner_id" in backup.import_record(shell)
        )
        if not imported:
            current = backup.validate(shell.result.config_path, archive)
            if current["sha256"] != shell._backup_validation["sha256"]:
                raise backup.BackupSetupError(
                    "backup_changed: the archive changed after review; go Back "
                    "and choose the backup again before applying."
                )
        if setup is None:
            backup.restore_local(shell, archive)
        else:
            backup.restore_server(shell, setup, archive)
        return backup.projects(shell)

    shell._run_checking(
        step=STEP_CONNECT,
        title="Restoring your backup.",
        message="Restoring the database, connecting, and reading its projects.",
        work=restore,
        on_success=lambda rows: _complete(shell, rows, setup),
        on_error=lambda exc: _failure(
            shell, exc, lambda: _apply(shell, archive, setup)
        ),
        group="onboard-backup-restore",
        blocks_quit=True,
    )


def _complete(shell, rows, setup) -> None:
    backup.record_restored(shell, rows)
    if setup is not None:
        from yoke_cli.config import onboard_wizard_run_connection as run_connection

        run_connection.record_self_host(shell, setup, kind=run_connection.KIND_RESTORED)
    resume_restored(shell)


def resume_restored(shell) -> None:
    """Offer this run's restored projects; the restore itself never repeats."""
    shell._restored_projects = backup.import_record(shell)["projects"]
    shell._restored_projects_offered = False
    # A completed restore is durable; Back cannot revisit old import consent.
    shell._history.clear()
    shell._goto_machine_github()


def resume_local_restore(shell) -> bool:
    """Continue past this run's finished local restore instead of offering it again."""
    record = backup.import_record(shell)
    if record.get("destination") != "local" or "projects" not in record:
        return False
    shell.result.admin_name = None
    resume_restored(shell)
    return True


def _failure(shell, exc, retry) -> None:
    from yoke_contracts.self_host_bootstrap_output import redact_api_tokens

    shell._goto(
        _View(
            SetupPrompt(
                key="connect.backup_failed",
                step=STEP_CONNECT,
                title="Backup setup needs attention.",
                message=redact_api_tokens(str(exc)),
                detail_lines=(
                    "The backup file is preserved. Correct the named problem, then retry.",
                ),
                choices=(
                    SelectionRow("retry", "Try again", "resume this step"),
                    SelectionRow("back", "Back", "choose another Yoke home"),
                ),
                tone=TONE_ERROR,
            ),
            lambda choice: (
                retry() if choice == "retry" else shell._return_to_destination_picker()
            ),
        )
    )

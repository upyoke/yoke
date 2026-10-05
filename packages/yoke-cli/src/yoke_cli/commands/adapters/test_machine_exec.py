"""``yoke test-machine exec``: run one ad hoc command on a registered Test Machine.

The endpoint is the test-machine capability's own host and user, read through
the registered ``test_machine.get``; SSH runs from this machine with its
ssh-agent identity. A host another session holds under its QA lease is
refused rather than disturbed mid-run.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_session_arg,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.config import machine_config
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher


EXEC_USAGE = "yoke test-machine exec --project P [--machine NAME] [--admin] [--session-id S] -- ARGV..."
_REFUSED_EXIT = 1


def _refuse(code: str, message: str, recovery: str) -> int:
    print(f"error: {code}: {message}", file=sys.stderr)
    print(f"recovery: {recovery}", file=sys.stderr)
    return _REFUSED_EXIT


def _lease_refusal(detail: dict[str, Any], session_id: str) -> int | None:
    lease = detail.get("active_lease")
    if not isinstance(lease, dict) or lease.get("session_id") == session_id:
        return None
    item = lease.get("item") if isinstance(lease.get("item"), dict) else {}
    holder = f"session {lease.get('session_id')}" + (
        f" for {item['ref']}" if item.get("ref") else ""
    )
    return _refuse(
        "test_machine_leased",
        f"{detail.get('machine')} is serially leased by {holder}, and an ad "
        "hoc command could disturb the run it holds the host for",
        "Wait for that lease to release, or ask its holder to run the "
        "command; a QA mission walker uses `yoke qa mission host-command`.",
    )


def test_machine_exec(args: List[str]) -> int:
    split = args.index("--") if "--" in args else len(args)
    command = args[split + 1 :]
    parser = argparse.ArgumentParser(
        prog="yoke test-machine exec",
        description=(
            "Run one command on a registered Test Machine over SSH, as the "
            "capability's user at its host. The words after `--` reach the "
            "remote login shell exactly as `ssh` sends them. Uses this "
            "machine's ssh-agent identity and pins host keys in a "
            "Yoke-managed known_hosts file; ~/.ssh is never read."
            " Streams stdout and stderr live, retaining only the last 64 KiB "
            "of each for failure diagnosis."
            " On macOS, keychain-backed harness CLIs (claude, cursor-agent) "
            "run through `yoke qa mission host-command --gui-session` "
            "under an awaiting mission's retained lease."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--machine")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Run through sudo on macOS or Linux using the machine's stored "
        "desktop_password administrator credential on private stdin. "
        "Output is redacted; the administrator command receives no stdin.",
    )
    add_session_arg(parser)
    parsed = parse_or_usage_error(parser, args[:split], EXEC_USAGE)
    if parsed is None:
        return 2
    if not command:
        print(f"usage: {EXEC_USAGE}", file=sys.stderr)
        print("the remote command goes after `--`", file=sys.stderr)
        return 2
    ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    response = call_dispatcher(
        function_id="test_machine.get",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "machine": parsed.machine},
        actor=actor,
    )
    if not response.success or not isinstance(response.result, dict):
        error = response.error
        return _refuse(
            error.code if error else "test_machine_unavailable",
            error.message if error else "test_machine.get returned no machine",
            (error.recovery_hint if error else None)
            or "`yoke test-machine list --project P` names the registered "
            "machines; pass one with --machine NAME.",
        )
    detail = response.result
    refused = _lease_refusal(detail, actor.session_id)
    if refused is not None:
        return refused
    settings = detail.get("settings") or {}
    from yoke_harness.test_machine_remote_exec import (
        RemoteExecRefusal,
        run_remote_command,
    )

    try:
        admin_options = {}
        if parsed.admin:
            from yoke_harness.test_machine_admin import administrator_password

            admin_options["administrator_password"] = administrator_password(
                project=parsed.project,
                machine=detail["machine"],
                os_name=settings["os"],
            )
        if settings["os"] == "windows":
            from yoke_harness.windows_wsl_command import windows_wsl_command

            command = [windows_wsl_command(" ".join(command))]
        completed = run_remote_command(
            host=str(settings["host"]),
            user=str(settings["user"]),
            command=command,
            yoke_home=machine_config.yoke_home(),
            **admin_options,
        )
    except RemoteExecRefusal as refusal:
        return _refuse(refusal.code, str(refusal), refusal.recovery)
    if parsed.admin and completed.returncode:
        _refuse(
            "test_machine_admin_command_failed",
            f"administrator command exited {completed.returncode}; see the redacted output above",
            "Correct the reported command failure and retry. If sudo rejected "
            "authentication, verify the registered user's sudo rights and "
            "reimport its administrator password as test-machine:NAME.desktop_password.",
        )
    if completed.returncode and settings["os"] == "macos":
        from yoke_harness.ssh_mac_gui_session import (
            classify_macos_session_context_failure,
        )

        failure = classify_macos_session_context_failure(completed, ssh_exec=True)
        if failure is not None:
            return _refuse(
                failure.error_code,
                failure.reason + "; this is an SSH session-context failure, "
                "not a sign-in diagnosis",
                "Verify the command through the GUI Terminal bridge first: "
                "`yoke qa mission host-command --execution-id ID "
                "--requirement-id N --gui-session -- ARGV...` under an awaiting "
                "mission's retained lease; diagnose sign-in only if it also "
                "fails there.",
            )
    return int(completed.returncode)


TOOL_SHAPED_SUBCOMMANDS = {("test-machine", "exec"): test_machine_exec}
TOOL_SHAPED_USAGE = {"yoke test-machine exec": EXEC_USAGE}


__all__ = [
    "EXEC_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "test_machine_exec",
]

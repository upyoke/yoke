"""Desktop access executes on the credential-owning client after authorization."""

from __future__ import annotations

import argparse
import json
import sys

from yoke_cli.commands._helpers import (
    add_session_arg,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef

DESKTOP_ACCESS_USAGE = (
    "yoke test-machine desktop-access --project P --test-machine TEST_MACHINE [--view]"
)


def test_machine_desktop_access(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke test-machine desktop-access",
        description=(
            "Open the registered RDP or VNC route and write the desktop password "
            "to a new mode-600 file under /tmp. Prints address, user and password_file. "
            "Linux and Windows WSL reuse or start XFCE and report desktop_session=started/reused/restarted. "
            "RDP access ends an orphaned fixture desktop older than xrdp-sesman and starts a replacement; "
            "a connected RDP client must close before that repair. "
            "Any second Linux viewer refuses linux_desktop_viewer_connected: close the open "
            "'Yoke desktop: MACHINE' viewer (or let browser authorize finish), then retry. "
            "Windows desktop_user and desktop_port name the WSL user and loopback xrdp service. "
            "--view opens that same XFCE display in FreeRDP's visible SDL client, feeds the fixture "
            "password on stdin, and closes the SSH forward when the viewer closes; no password file. "
            "On the loopback SSH route, SSH host-key verification is the trust boundary: /cert:ignore "
            "avoids FreeRDP's per-port certificate cache. Direct RDP retains certificate verification. "
            "On macOS it uses SDL OpenGL rendering to keep input responsive during continuous updates. "
            "It announces and retains a mode-600, password-redacted INFO client log, returned as log_path. "
            "A connected client's logged local cancellation closes successfully; client_exit_code preserves "
            "FreeRDP's status. Failures or forced-stop hangs name the retained log and recovery. "
            "Install FreeRDP only for desktop_rdp_client_missing; remote logoff names the sesman log to inspect. "
            "if startup refuses, repair the registered fixture secret or xrdp/XFCE and rerun. "
            "For SSH forwarding the control socket is PASSWORD_FILE.ssh; close it with "
            "ssh -S PASSWORD_FILE.ssh -O exit SSH_USER@SSH_HOST after connecting. "
            "Remove the private password copy after use."
            " A session holding a live steering seat on the project can assist an actively leased "
            "desktop without taking or releasing its lease; any other session must own the lease and "
            "otherwise receives steering_seat_required. The output names the assisting operator, "
            "seat and lease; authorization is audited in the holder's session history."
        ),
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project that owns the test machine.",
    )
    parser.add_argument(
        "--test-machine",
        metavar="TEST_MACHINE",
        required=True,
        help="Test machine to open, by name.",
    )
    parser.add_argument(
        "--view",
        action="store_true",
        help="Open the desktop in a visible FreeRDP viewer window.",
    )
    add_session_arg(parser)
    parsed = parse_or_usage_error(parser, args, DESKTOP_ACCESS_USAGE)
    if parsed is None:
        return 2
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="test_machine.desktop_access",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "test_machine": parsed.test_machine},
        actor=build_actor(session_id=parsed.session_id),
    )
    if not response.success:
        error = response.error
        print(f"error: {error.code}: {error.message}", file=sys.stderr)
        if error.recovery_hint:
            print(f"recovery: {error.recovery_hint}", file=sys.stderr)
        return 1
    from yoke_cli.config.capability_secrets import MachineCapabilitySecretError
    from yoke_harness.desktop_access import DesktopAccessError, open_desktop_access

    try:
        route = dict(response.result)
        operator_access = route.pop("operator_access", None)
        if operator_access:
            print(
                f"Desktop access authorized for {operator_access['actor_name']} "
                f"(actor {operator_access['actor_id']}) alongside lease "
                f"{operator_access['lease_id']}; lease unchanged.",
                file=sys.stderr,
            )
            if operator_access.get("audit_recovery"):
                print(operator_access["audit_recovery"], file=sys.stderr)
        result = open_desktop_access(**route, view=parsed.view)
        if operator_access:
            result["operator_access"] = operator_access
        print(json.dumps(result))
    except (DesktopAccessError, MachineCapabilitySecretError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


USAGE_BY_FUNCTION_ID = {"test_machine.desktop_access": DESKTOP_ACCESS_USAGE}

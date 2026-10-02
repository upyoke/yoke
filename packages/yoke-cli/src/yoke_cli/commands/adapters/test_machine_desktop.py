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

DESKTOP_ACCESS_USAGE = "yoke test-machine desktop-access --project P --machine NAME"


def test_machine_desktop_access(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke test-machine desktop-access",
        description=(
            "Open the registered RDP or VNC route and write the desktop password "
            "to a new mode-600 file under /tmp. Prints address, user and password_file. "
            "Linux reuses or starts XFCE and also reports desktop_session=started/reused; human RDP login is the fallback. "
            "For SSH forwarding the control socket is PASSWORD_FILE.ssh; close it with "
            "ssh -S PASSWORD_FILE.ssh -O exit SSH_USER@SSH_HOST after connecting. "
            "Remove the private password copy after use."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--machine", required=True)
    add_session_arg(parser)
    parsed = parse_or_usage_error(parser, args, DESKTOP_ACCESS_USAGE)
    if parsed is None:
        return 2
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="test_machine.desktop_access",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "machine": parsed.machine},
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
        print(json.dumps(open_desktop_access(**response.result)))
    except (DesktopAccessError, MachineCapabilitySecretError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


USAGE_BY_FUNCTION_ID = {"test_machine.desktop_access": DESKTOP_ACCESS_USAGE}

"""Authorize one identity on a registered Test Machine from this workstation."""

from __future__ import annotations

import json
import sys

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    parse_identity_declarations,
    select_identity,
)
from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.config import browser_profile, machine_config
from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError
from yoke_cli.config.capability_secrets import read_machine_capability_secret
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    test_machine_capability_type,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher


def _read(function, payload, actor):
    response = call_dispatcher(
        function_id=function,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=actor,
    )
    if response.success and isinstance(response.result, dict):
        return response.result
    error = response.error
    if (
        function == "projects.capability_settings.get"
        and error
        and error.code == "not_found"
    ):
        return {"settings_json": "{}"}
    raise RuntimeError(
        f"{error.code if error else 'browser_authorize_remote_unavailable'}: "
        f"{error.message if error else function + ' returned no result'}. "
        + (
            (error.recovery_hint if error else None)
            or "Check `yoke env list` and `yoke test-machine list --project P`, then retry."
        )
    )


def _sign_in_accounts(identity) -> str:
    accounts = []
    for site in identity.sites:
        if site.account and site.account not in accounts:
            accounts.append(site.account)
    return ", ".join(accounts) if accounts else identity.name


def _desktop_command(project, machine, settings) -> str:
    from yoke_contracts.machine_config.desktop_access import validate_desktop_settings

    viewable = False
    try:
        route = validate_desktop_settings(settings)
    except TestMachineCapabilityError:
        route = {}
    if (
        route
        and settings.get("os") in {"linux", "windows"}
        and route.get("desktop_protocol") == "rdp"
    ):
        viewable = True
    flag = " --view" if viewable else ""
    return (
        f"yoke test-machine desktop-access --project {project} "
        f"--machine {machine}{flag}"
    )


def _tell(message, json_mode) -> None:
    print(message, file=sys.stderr if json_mode else sys.stdout, flush=True)


def _open_sign_in_viewer(project, detail, identity, json_mode):
    from yoke_harness.desktop_access import DesktopAccessError, begin_desktop_view

    settings = detail["settings"]
    machine = detail["machine"]
    try:
        viewer = begin_desktop_view(project=project, machine=machine, settings=settings)
    except (DesktopAccessError, TestMachineCapabilityError) as exc:
        command = _desktop_command(project, machine, settings)
        _tell(
            f"{exc}\nRun `{command}`.\n"
            "Sign in on its desktop, then close the browser window; "
            "the command verifies there before returning.",
            json_mode,
        )
        return None
    _tell(
        f"Opening the desktop of machine {machine}. A window titled "
        f'"Yoke desktop: {machine}" will appear.\n'
        f"Sign in with {_sign_in_accounts(identity)}.\n"
        "Close the browser window when done; the viewer closes when "
        "verification finishes.",
        json_mode,
    )
    return viewer


def _close_sign_in_viewer(viewer, machine) -> None:
    from yoke_harness.desktop_access import DesktopAccessError

    try:
        viewer.close()
    except DesktopAccessError as exc:
        print(
            f"Close the desktop viewer for machine {machine} yourself: {exc}",
            file=sys.stderr,
            flush=True,
        )


def authorize_remote(parsed) -> int:
    from yoke_harness.test_machine_gui_command import run_gui_command
    from yoke_harness.test_machine_remote_exec import RemoteExecRefusal

    try:
        if parsed.declarations_json is not None:
            raise BrowserIdentityError(
                "browser_authorize_machine_declarations_conflict: --machine reads "
                "settings from the control plane; omit --declarations-json. For a "
                "host without a route, run locally there with --declarations-json."
            )
        project = browser_profile.profile_project_key(parsed.project)
        ensure_handlers_loaded()
        actor = build_actor()
        detail = _read(
            "test_machine.get", {"project": project, "machine": parsed.machine}, actor
        )
        lease = detail.get("active_lease")
        if isinstance(lease, dict) and lease.get("session_id") != actor.session_id:
            raise RuntimeError(
                "test_machine_leased: machine "
                + str(detail.get("machine"))
                + " is leased by session "
                + str(lease.get("session_id"))
                + ". Wait for its lease to release, or ask the holder to authorize "
                "the identity; sign-in stops every automated browser on that host."
            )
        settings = (
            _read(
                "projects.capability_settings.get",
                {"project": project, "cap_type": "browser-control"},
                actor,
            ).get("settings_json")
            or "{}"
        )
        try:
            declarations = (
                json.loads(settings) if isinstance(settings, str) else settings
            )
            if not isinstance(declarations, dict):
                raise ValueError("expected a browser-control settings object")
        except ValueError as exc:
            raise BrowserIdentityError(
                "browser_identity_declarations_unreadable: "
                + str(exc)
                + ". Repair `yoke projects capability-settings set --project P "
                "--cap-type browser-control`, then retry."
            ) from None
        identity = select_identity(
            parse_identity_declarations(declarations), parsed.identity
        )
        argv = [
            "yoke",
            "browser",
            "authorize",
            "--project",
            project,
            "--identity",
            identity.name,
            "--declarations-json",
            json.dumps(declarations),
        ]
        if parsed.url is not None:
            argv += ["--url", parsed.url]
        if parsed.reset:
            argv.append("--reset")
        if parsed.json_mode:
            argv.append("--json")
        viewer = _open_sign_in_viewer(project, detail, identity, parsed.json_mode)
        try:
            desktop_password = (
                read_machine_capability_secret(
                    project,
                    test_machine_capability_type(detail["machine"]),
                    "desktop_password",
                )
                if detail["settings"].get("os") in {"linux", "windows"}
                else None
            )
            result = run_gui_command(
                settings=detail["settings"],
                argv=argv,
                yoke_home=machine_config.yoke_home(),
                desktop_password=desktop_password,
            )
        finally:
            if viewer is not None:
                _close_sign_in_viewer(viewer, detail["machine"])
        if parsed.json_mode:
            try:
                payload = json.loads(result.stdout)
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("ok"), bool
                ):
                    raise ValueError("missing authorization outcome")
                if payload["ok"] != (result.returncode == 0):
                    raise ValueError("outcome disagrees with remote exit status")
            except ValueError:
                raise RuntimeError(
                    "browser_authorize_remote_receipt_invalid: machine "
                    f"{detail['machine']} returned no consistent authorization receipt "
                    f"(exit {result.returncode}). "
                    + result.stderr.strip()
                    + ". Check its installed Yoke and GUI session, then retry."
                ) from None
            payload["machine"] = detail["machine"]
            print(json.dumps(payload))
        else:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            if result.returncode:
                print(
                    f"browser_authorize_remote_failed: machine {detail['machine']} "
                    f"exited {result.returncode}. Repair the reported site, runtime "
                    "or GUI-session failure and rerun this --machine command.",
                    file=sys.stderr,
                )
        return int(result.returncode)
    except (
        ProjectSlugLookupError,
        BrowserIdentityError,
        TestMachineCapabilityError,
        RuntimeError,
        OSError,
    ) as exc:
        message = (
            f"{exc.code}: {exc}. {exc.recovery}"
            if isinstance(exc, RemoteExecRefusal)
            else str(exc)
        )
        if parsed.json_mode:
            print(json.dumps({"ok": False, "error": message}))
        else:
            print(f"yoke browser authorize: {message}", file=sys.stderr)
        return 2

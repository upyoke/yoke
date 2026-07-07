"""Tool-shaped ``yoke core`` local-core launcher commands."""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.local_core.launcher import (
    DEFAULT_API_PORT,
    DEFAULT_POSTGRES_PORT,
    LocalCoreLauncher,
)

AdapterFn = Callable[[List[str]], int]

CORE_USAGE = {
    "yoke core build": (
        "Build a local Yoke core image from an explicit source checkout."
    ),
    "yoke core start": (
        "Start local Postgres + Yoke API containers and configure local-core env."
    ),
    "yoke core status": (
        "Report installed/running/healthy state and typed setup guidance."
    ),
    "yoke core logs": "Print local-core API and Postgres container logs.",
    "yoke core stop": "Stop local-core containers without deleting volumes.",
    "yoke core upgrade": (
        "Run server-side bootstrap and restart API with an explicit "
        "local/private image."
    ),
}


def core_build(args: List[str]) -> int:
    parser = _parser("build", CORE_USAGE["yoke core build"])
    parser.add_argument(
        "--checkout",
        required=True,
        help="Yoke source checkout path.",
    )
    _add_image(parser)
    _add_ports(parser)
    _add_json(parser)
    _add_machine_home(parser)
    _add_dry_run(parser)
    parsed = _parse(parser, args, "yoke core build --checkout PATH [--dry-run]")
    if parsed is None:
        return 2
    payload = _launcher(parsed).build(
        checkout_path=parsed.checkout,
        image=parsed.image,
        api_port=parsed.api_port,
        postgres_port=parsed.postgres_port,
        dry_run=parsed.dry_run,
    )
    return _emit(payload, parsed.json_mode)


def core_start(args: List[str]) -> int:
    parser = _parser("start", CORE_USAGE["yoke core start"])
    _add_image(parser)
    _add_ports(parser)
    _add_json(parser)
    _add_machine_home(parser)
    _add_dry_run(parser)
    parser.add_argument("--config", default=None, help="Machine config path.")
    parser.add_argument(
        "--from-checkout",
        default=None,
        help="Build image from this Yoke source checkout before starting.",
    )
    parser.add_argument("--build", action="store_true", help="Build before starting.")
    parser.add_argument(
        "--start-colima",
        action="store_true",
        help="On macOS, start Colima when Docker is unavailable.",
    )
    parsed = _parse(
        parser,
        args,
        "yoke core start [--from-checkout PATH --build] "
        "[--image IMAGE] [--dry-run]",
    )
    if parsed is None:
        return 2
    payload = _launcher(parsed).start(
        image=parsed.image,
        api_port=parsed.api_port,
        postgres_port=parsed.postgres_port,
        config_path=parsed.config,
        from_checkout=parsed.from_checkout,
        build=parsed.build,
        start_colima=parsed.start_colima,
        dry_run=parsed.dry_run,
    )
    return _emit(payload, parsed.json_mode)


def core_status(args: List[str]) -> int:
    parser = _parser("status", CORE_USAGE["yoke core status"])
    _add_json(parser)
    _add_machine_home(parser)
    parsed = _parse(parser, args, "yoke core status [--json]")
    if parsed is None:
        return 2
    return _emit(_launcher(parsed).status(), parsed.json_mode)


def core_logs(args: List[str]) -> int:
    parser = _parser("logs", CORE_USAGE["yoke core logs"])
    _add_json(parser)
    _add_machine_home(parser)
    parser.add_argument("--tail", type=int, default=120, help="Lines per container.")
    parsed = _parse(parser, args, "yoke core logs [--tail N]")
    if parsed is None:
        return 2
    return _emit(_launcher(parsed).logs(tail=parsed.tail), parsed.json_mode)


def core_stop(args: List[str]) -> int:
    parser = _parser("stop", CORE_USAGE["yoke core stop"])
    _add_json(parser)
    _add_machine_home(parser)
    _add_dry_run(parser)
    parsed = _parse(parser, args, "yoke core stop [--dry-run]")
    if parsed is None:
        return 2
    return _emit(_launcher(parsed).stop(dry_run=parsed.dry_run), parsed.json_mode)


def core_upgrade(args: List[str]) -> int:
    parser = _parser("upgrade", CORE_USAGE["yoke core upgrade"])
    _add_json(parser)
    _add_machine_home(parser)
    _add_dry_run(parser)
    _add_image(parser)
    parser.add_argument(
        "--from-checkout",
        default=None,
        help="Build image from this Yoke source checkout before upgrading.",
    )
    parser.add_argument("--build", action="store_true", help="Build before upgrading.")
    parser.add_argument("--config", default=None, help="Machine config path.")
    parsed = _parse(
        parser,
        args,
        "yoke core upgrade [--from-checkout PATH --build] "
        "[--image IMAGE] [--dry-run]",
    )
    if parsed is None:
        return 2
    payload = _launcher(parsed).upgrade(
        image=parsed.image,
        from_checkout=parsed.from_checkout,
        build=parsed.build,
        config_path=parsed.config,
        dry_run=parsed.dry_run,
    )
    return _emit(payload, parsed.json_mode)


def _parser(command: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=f"yoke core {command}",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _add_image(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--image",
        default=None,
        help="Already-built local/private Yoke core image tag.",
    )


def _add_ports(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    parser.add_argument("--postgres-port", type=int, default=DEFAULT_POSTGRES_PORT)


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", dest="json_mode", action="store_true")


def _add_machine_home(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--machine-home",
        default=None,
        help="Override ~/.yoke for tests or machine-local setup.",
    )


def _add_dry_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Print plan only.")


def _parse(
    parser: argparse.ArgumentParser,
    args: List[str],
    usage: str,
) -> argparse.Namespace | None:
    return parse_or_usage_error(parser, args, usage)


def _launcher(parsed: argparse.Namespace) -> LocalCoreLauncher:
    return LocalCoreLauncher(machine_home=parsed.machine_home)


def _emit(payload: dict[str, Any], json_mode: bool) -> int:
    if json_mode:
        print(json.dumps(payload, sort_keys=True))
    else:
        _emit_human(payload)
    return 0 if payload.get("ok") else 1


def _emit_human(payload: dict[str, Any]) -> None:
    state = "ok" if payload.get("ok") else "needs attention"
    print(f"yoke core {payload.get('action')}: {state}")
    api = payload.get("api") or {}
    if api.get("url"):
        print(f"api: {api['url']}")
    for issue in payload.get("issues") or []:
        print(f"- {issue['code']}: {issue['message']}")
        print(f"  {issue['guidance']}")
    plan = payload.get("plan") or []
    if plan:
        print("plan:")
        for cmd in plan:
            print("  " + " ".join(cmd))
    logs = payload.get("logs") or {}
    for name, text in logs.items():
        print(f"== {name} ==")
        print(text)


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("core", "build"): core_build,
    ("core", "start"): core_start,
    ("core", "status"): core_status,
    ("core", "logs"): core_logs,
    ("core", "stop"): core_stop,
    ("core", "upgrade"): core_upgrade,
}


__all__ = [
    "CORE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "core_build",
    "core_logs",
    "core_start",
    "core_status",
    "core_stop",
    "core_upgrade",
]

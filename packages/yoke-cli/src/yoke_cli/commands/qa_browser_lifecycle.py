"""Tool-shaped Browser QA daemon setup/status commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, List

from yoke_cli import browser_node_toolchain
from yoke_cli.commands._helpers import parse_or_usage_error


QA_BROWSER_STATUS_USAGE = "yoke qa browser status [--project PROJECT] [--json]"
QA_BROWSER_SETUP_USAGE = (
    "yoke qa browser setup [--dry-run] [--project PROJECT] [--port PORT] "
    "[--headed] [--idle-timeout SECONDS] [--json]"
)
MILLISECONDS_PER_SECOND = 1000


def qa_browser_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser status",
        description=QA_BROWSER_STATUS_USAGE,
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_STATUS_USAGE)
    if parsed is None:
        return 2

    try:
        from yoke_harness import browser_client, browser_runtime_home
    except ImportError as exc:
        print(
            "yoke qa browser status requires yoke-harness in the "
            f"product install: {exc}",
            file=sys.stderr,
        )
        return 2

    payload = _browser_readiness(
        browser_client, browser_runtime_home, project=parsed.project,
    )
    if parsed.json_mode:
        print(json.dumps(payload))
    else:
        print(_format_status_human(payload))
    return 0


def _format_status_human(payload: dict[str, object]) -> str:
    """Render the readiness facts as a human-readable status report.

    Surfaces the same facts as ``--json`` (runtime dir, node toolchain, npm
    dependencies, chromium, daemon) plus repair guidance, so an operator does
    not need ``--json`` to see why browser QA is not ready.
    """
    node = payload.get("node", {})
    deps = payload.get("npm_dependencies", {})
    chromium = payload.get("chromium", {})
    daemon = payload.get("daemon", {})
    profile = payload.get("profile", {})
    lines = [
        f"runtime dir:      {payload.get('runtime_dir', 'unknown')}",
        f"materialized:     {'yes' if payload.get('materialized') else 'no'}",
        f"node:             {_facet(node)}",
        f"npm dependencies: {deps.get('status', 'unknown')}",
        f"chromium:         {chromium.get('status', 'unknown')}",
        f"daemon:           {daemon.get('status', 'unknown')}",
        f"profile:          {profile.get('status', 'unknown')} "
        f"({profile.get('project', 'unknown')}) {profile.get('path', '')}",
    ]
    repairs = payload.get("repairs") or []
    if repairs:
        lines.append("repairs:")
        lines.extend(f"  - {hint}" for hint in repairs)
    return "\n".join(lines)


def _facet(facet: dict[str, object]) -> str:
    """Render one readiness facet, naming where a provisioned tool came from."""
    status = facet.get("status", "unknown")
    version = facet.get("version")
    source = facet.get("source")
    rendered = f"{status} ({version})" if version else str(status)
    return f"{rendered} [{source}]" if source and version else rendered


def qa_browser_setup(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser setup",
        description=QA_BROWSER_SETUP_USAGE,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--idle-timeout", type=int, default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_SETUP_USAGE)
    if parsed is None:
        return 2

    try:
        from yoke_harness import browser_client, browser_runtime_home
    except ImportError as exc:
        print(
            "yoke qa browser setup requires yoke-harness in the "
            f"product install: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        runtime_dir = browser_runtime_home.ensure_materialized()
        prerequisite_actions: list[dict[str, str]] = []
        if not parsed.dry_run:
            prerequisite_actions = _ensure_node_toolchain(
                emit=lambda line: print(line, file=sys.stderr)
            )
        readiness = _browser_readiness(
            browser_client, browser_runtime_home, project=parsed.project,
        )
        if parsed.dry_run:
            result = {
                "ok": True,
                "dry_run": True,
                "runtime_dir": str(runtime_dir),
                "daemon": readiness["daemon"],
                "readiness": readiness,
            }
        else:
            result = {
                "ok": True,
                "dry_run": False,
                "runtime_dir": str(runtime_dir),
                "prerequisite_actions": prerequisite_actions,
                "daemon": browser_client.daemon_start(
                    profile_dir=_profile_dir_arg(parsed.project),
                    port=parsed.port,
                    headed=parsed.headed,
                    idle_timeout=(
                        parsed.idle_timeout * MILLISECONDS_PER_SECOND
                        if parsed.idle_timeout is not None
                        else None
                    ),
                ),
            }
    except RuntimeError as exc:
        failure: dict[str, object] = {"ok": False, "error": str(exc)}
        if isinstance(exc, browser_node_toolchain.NodeToolchainError):
            failure["error_code"] = exc.code
            failure["recovery"] = exc.recovery
        if parsed.json_mode:
            print(json.dumps(failure))
        else:
            print(f"yoke qa browser setup: {exc}", file=sys.stderr)
        return 2

    if parsed.json_mode:
        print(json.dumps(result))
    else:
        daemon = result.get("daemon") or result.get("readiness", {}).get("daemon", {})
        print(daemon.get("status", "ready"))
    return 0


def _profile_dir_arg(project: str | None) -> str | None:
    """The authorized profile the daemon should launch, or ``None`` for clean."""
    from yoke_cli.config.browser_profile import authorized_profile_dir

    authorized = authorized_profile_dir(project)
    return str(authorized) if authorized is not None else None


def _profile_readiness(project: str | None) -> dict[str, object]:
    """Report which project profile a daemon started here would open.

    Status is a diagnostic surface, so a project reference that does not
    resolve to a slug is reported as the unresolved facet it is rather than
    raised — the operator asked what this machine would open, and "the project
    could not be named" is that answer.
    """
    from yoke_cli.config import browser_profile
    from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError

    try:
        directory = browser_profile.profile_dir(project)
        key = browser_profile.profile_project_key(project)
    except ProjectSlugLookupError as exc:
        return {"project": "unresolved", "path": "", "status": str(exc)}
    return {
        "project": key,
        "path": str(directory),
        "status": "authorized" if directory.is_dir() else "not authorized",
    }


def _browser_readiness(
    browser_client, browser_runtime_home, project: str | None = None,
) -> dict[str, object]:
    runtime_dir = browser_runtime_home.runtime_dir()
    expected_hash = browser_runtime_home.source_hash()
    marker = runtime_dir / browser_runtime_home.HASH_MARKER_NAME
    current_hash = _read_text(marker)
    node = browser_node_toolchain.toolchain_status()
    deps_ready = (runtime_dir / "node_modules" / "playwright").is_dir()
    chromium = _chromium_status(runtime_dir) if deps_ready and node["ok"] else "unknown"
    repairs = _repair_hints(node, deps_ready, chromium)
    return {
        "runtime_dir": str(runtime_dir),
        "source_hash": expected_hash,
        "materialized": current_hash == expected_hash,
        "node": node,
        "npm_dependencies": {"status": "ready" if deps_ready else "missing"},
        "chromium": {"status": chromium},
        "daemon": browser_client.daemon_status(),
        "profile": _profile_readiness(project),
        "repairs": repairs,
    }


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _chromium_status(runtime_dir: Path) -> str:
    from yoke_harness import browser_runtime_home

    toolchain = browser_node_toolchain.resolve_node_toolchain()
    if toolchain is None:
        return "unknown"
    result = subprocess.run(
        [str(toolchain.node), "-e", browser_runtime_home.CHROMIUM_PRESENT_PROBE_JS],
        cwd=runtime_dir,
        capture_output=True,
        text=True,
        check=False,
        env=toolchain.command_env(),
    )
    probe = result.stdout.strip() if result.returncode == 0 else "missing"
    return "ready" if probe == "ok" else "missing"


def _ensure_node_toolchain(*, emit: Callable[[str], None]) -> list[dict[str, str]]:
    """Resolve or provision the Node toolchain, naming what setup had to do."""
    before = browser_node_toolchain.resolve_node_toolchain()
    toolchain = browser_node_toolchain.ensure_node_toolchain(emit=emit)
    if before is not None:
        return []
    return [
        {
            "action": "provision-node",
            "source": toolchain.source,
            "version": toolchain.version,
            "bin_dir": str(toolchain.bin_dir),
        }
    ]


def _repair_hints(
    node: dict[str, object], deps_ready: bool, chromium: str
) -> list[str]:
    hints: list[str] = []
    if not node["ok"]:
        hints.append(
            "Run `yoke qa browser setup`; it provisions Node.js "
            f"{browser_node_toolchain.MANAGED_NODE_VERSION} for this host when "
            "none is available."
        )
    if not deps_ready:
        hints.append("Run `yoke qa browser setup` to install browser runtime npm dependencies.")
    if chromium != "ready":
        hints.append("Run `yoke qa browser setup`; on Linux this may need sudo/package-manager access for Playwright OS dependencies.")
    return hints


QA_BROWSER_LIFECYCLE_SUBCOMMANDS = {
    ("qa", "browser", "setup"): qa_browser_setup,
    ("qa", "browser", "status"): qa_browser_status,
}

QA_BROWSER_LIFECYCLE_USAGE = {
    "yoke qa browser setup": (
        "Materialize and optionally start the machine-local Browser QA daemon."
    ),
    "yoke qa browser status": (
        "Report the machine-local Browser QA daemon status."
    ),
}


__all__ = [
    "QA_BROWSER_LIFECYCLE_SUBCOMMANDS",
    "QA_BROWSER_LIFECYCLE_USAGE",
    "QA_BROWSER_SETUP_USAGE",
    "QA_BROWSER_STATUS_USAGE",
    "qa_browser_setup",
    "qa_browser_status",
]

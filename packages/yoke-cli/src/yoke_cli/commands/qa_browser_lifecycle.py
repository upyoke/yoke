"""Tool-shaped Browser QA daemon setup/status commands."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error


QA_BROWSER_STATUS_USAGE = "yoke qa browser status [--json]"
QA_BROWSER_SETUP_USAGE = (
    "yoke qa browser setup [--dry-run] [--port PORT] [--headed] "
    "[--idle-timeout SECONDS] [--json]"
)


def qa_browser_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser status",
        description=QA_BROWSER_STATUS_USAGE,
    )
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

    payload = _browser_readiness(browser_client, browser_runtime_home)
    if parsed.json_mode:
        print(json.dumps(payload))
    else:
        print(_format_status_human(payload))
    return 0


def _format_status_human(payload: dict[str, object]) -> str:
    """Render the readiness facts as a human-readable status report.

    Surfaces the same facts as ``--json`` (runtime dir, node, npm,
    npm dependencies, chromium, daemon) plus repair guidance, so an
    operator does not need ``--json`` to see why browser QA is not ready.
    """
    node = payload.get("node", {})
    npm = payload.get("npm", {})
    deps = payload.get("npm_dependencies", {})
    chromium = payload.get("chromium", {})
    daemon = payload.get("daemon", {})
    lines = [
        f"runtime dir:      {payload.get('runtime_dir', 'unknown')}",
        f"materialized:     {'yes' if payload.get('materialized') else 'no'}",
        f"node:             {_facet(node)}",
        f"npm:              {_facet(npm)}",
        f"npm dependencies: {deps.get('status', 'unknown')}",
        f"chromium:         {chromium.get('status', 'unknown')}",
        f"daemon:           {daemon.get('status', 'unknown')}",
    ]
    repairs = payload.get("repairs") or []
    if repairs:
        lines.append("repairs:")
        lines.extend(f"  - {hint}" for hint in repairs)
    return "\n".join(lines)


def _facet(facet: dict[str, object]) -> str:
    status = facet.get("status", "unknown")
    version = facet.get("version")
    return f"{status} ({version})" if version else str(status)


def qa_browser_setup(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser setup",
        description=QA_BROWSER_SETUP_USAGE,
    )
    parser.add_argument("--dry-run", action="store_true")
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
            prerequisite_actions = _ensure_node_prerequisites()
        readiness = _browser_readiness(browser_client, browser_runtime_home)
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
                    port=parsed.port,
                    headed=parsed.headed,
                    idle_timeout=parsed.idle_timeout,
                ),
            }
    except RuntimeError as exc:
        if parsed.json_mode:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"yoke qa browser setup: {exc}", file=sys.stderr)
        return 2

    if parsed.json_mode:
        print(json.dumps(result))
    else:
        daemon = result.get("daemon") or result.get("readiness", {}).get("daemon", {})
        print(daemon.get("status", "ready"))
    return 0


def _browser_readiness(browser_client, browser_runtime_home) -> dict[str, object]:
    runtime_dir = browser_runtime_home.runtime_dir()
    expected_hash = browser_runtime_home.source_hash()
    marker = runtime_dir / browser_runtime_home.HASH_MARKER_NAME
    current_hash = _read_text(marker)
    node = _command_version(["node", "--version"], minimum_major=18)
    npm = _command_version(["npm", "--version"])
    deps_ready = (runtime_dir / "node_modules" / "playwright").is_dir()
    chromium = _chromium_status(runtime_dir) if deps_ready and node["ok"] else "unknown"
    repairs = _repair_hints(node, npm, deps_ready, chromium)
    return {
        "runtime_dir": str(runtime_dir),
        "source_hash": expected_hash,
        "materialized": current_hash == expected_hash,
        "node": node,
        "npm": npm,
        "npm_dependencies": {"status": "ready" if deps_ready else "missing"},
        "chromium": {"status": chromium},
        "daemon": browser_client.daemon_status(),
        "repairs": repairs,
    }


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _command_version(command: list[str], minimum_major: int | None = None) -> dict[str, object]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        return {"ok": False, "status": "missing", "error": str(exc)}
    version = result.stdout.strip()
    ok = result.returncode == 0
    if ok and minimum_major is not None:
        major = version.lstrip("v").split(".", 1)[0]
        ok = major.isdigit() and int(major) >= minimum_major
    return {"ok": ok, "status": "ready" if ok else "unsupported", "version": version}


def _chromium_status(runtime_dir: Path) -> str:
    script = (
        "try { var pw = require('./node_modules/playwright'); "
        "var fs = require('fs'); process.stdout.write(fs.existsSync("
        "pw.chromium.executablePath()) ? 'ready' : 'missing'); } "
        "catch(e) { process.stdout.write('missing'); }"
    )
    result = subprocess.run(["node", "-e", script], cwd=runtime_dir, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "missing"


def _ensure_node_prerequisites() -> list[dict[str, str]]:
    node = _command_version(["node", "--version"], minimum_major=18)
    npm = _command_version(["npm", "--version"])
    if node["ok"] and npm["ok"]:
        return []
    if sys.platform != "darwin":
        raise RuntimeError(
            "Node.js 18+ and npm are required. Install them with your system "
            "package manager, then rerun `yoke qa browser setup`."
        )
    brew = _find_homebrew()
    if brew is None:
        raise RuntimeError(
            "Node.js 18+ and npm are required. Install Homebrew or Node.js "
            "18+, then rerun `yoke qa browser setup`."
        )
    result = subprocess.run(
        [brew, "install", "node"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            "Homebrew could not install Node.js for Browser QA setup"
            + (f": {detail}" if detail else ".")
        )
    node = _command_version(["node", "--version"], minimum_major=18)
    npm = _command_version(["npm", "--version"])
    if not node["ok"] or not npm["ok"]:
        raise RuntimeError(
            "Homebrew completed, but Node.js 18+ and npm are still not "
            "available on PATH. Open a new shell or add Homebrew to PATH, "
            "then rerun `yoke qa browser setup`."
        )
    return [{"action": "install-node", "manager": "homebrew"}]


def _find_homebrew() -> str | None:
    found = shutil.which("brew")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if Path(candidate).is_file():
            return candidate
    return None


def _repair_hints(node: dict[str, object], npm: dict[str, object], deps_ready: bool, chromium: str) -> list[str]:
    hints: list[str] = []
    if not node["ok"]:
        hints.append("Install Node.js 18+ and npm, then run `yoke qa browser setup`.")
    if not npm["ok"]:
        hints.append("Install npm, then run `yoke qa browser setup`.")
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

"""Read-only Pack tool prerequisite probes for local machine workflows."""

from __future__ import annotations

import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from yoke_contracts.packs import validate_pack_prerequisites


PROBE_TIMEOUT_SECONDS = 15.0
READY_STATUS = "ready"
_VERSION = re.compile(r"(?<![0-9])(\d+(?:\.\d+){1,3})(?![0-9])")
_RUN = subprocess.run
_SYSTEM = platform.system
_WHICH = shutil.which


def probe_prerequisites(
    prerequisites: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Probe validated declarations without modifying the machine."""
    declarations = validate_pack_prerequisites(prerequisites)
    return [_probe_one(declaration) for declaration in declarations]


def probe_pack_prerequisites(
    packs: list[tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Probe Pack-tagged declarations once per distinct contract."""
    cache: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for slug, raw_declarations in packs:
        for declaration in validate_pack_prerequisites(raw_declarations):
            key = json.dumps(declaration, sort_keys=True, separators=(",", ":"))
            if key not in cache:
                cache[key] = _probe_one(declaration)
            rows.append({"pack": slug, **cache[key]})
    return rows


def collect_installed_pack_prerequisites(
    repo_root: str | Path,
) -> list[dict[str, Any]]:
    """Report every prerequisite recorded by installed Packs in a checkout."""
    from yoke_cli.packs.receipt import PackReceiptError, load_receipt

    root = Path(repo_root).expanduser().resolve()
    try:
        receipt = load_receipt(root)
    except PackReceiptError as exc:
        return [
            {
                "pack": "*",
                "tool": "pack-receipt",
                "status": "error",
                "code": "pack-prerequisite-receipt-invalid",
                "detail": str(exc),
                "install_recipe": (
                    "Repair .yoke/packs.json, then rerun the machine inventory."
                ),
            }
        ]
    if receipt is None:
        return []
    return probe_pack_prerequisites(
        [
            (slug, record["prerequisites"])
            for slug, record in sorted(receipt["packs"].items())
        ]
    )


def unsatisfied_prerequisites(
    rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return rows that did not produce a usable version at the floor."""
    return [dict(row) for row in rows if row.get("status") != READY_STATUS]


def _probe_one(declaration: Mapping[str, Any]) -> dict[str, Any]:
    tool = str(declaration["tool"])
    minimum = str(declaration["minimum_version"])
    probe = declaration["probe"]
    executable_name = str(probe["executable"])
    command = [executable_name, *probe["version_args"]]
    result = {
        **dict(declaration),
        "version_command": command,
        "install_recipe": _install_recipe(declaration["install"]),
        "observed_version": None,
    }
    executable = _WHICH(executable_name)
    if not executable:
        return {
            **result,
            "status": "missing",
            "code": "pack-prerequisite-missing",
            "detail": (
                f"{tool} {minimum} or newer is required, but "
                f"{executable_name!r} is not on PATH."
            ),
        }
    try:
        completed = _RUN(
            (executable, *probe["version_args"]),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            **result,
            "status": "unusable",
            "code": "pack-prerequisite-unusable",
            "detail": f"{tool} could not run its version probe: {_diagnostic(exc)}",
        }
    output = _diagnostic(completed.stdout)
    if completed.returncode != 0:
        return {
            **result,
            "status": "unusable",
            "code": "pack-prerequisite-unusable",
            "detail": (f"{tool} version probe exited {completed.returncode}: {output}"),
        }
    observed = _observed_version(output)
    if observed is None:
        return {
            **result,
            "status": "unusable",
            "code": "pack-prerequisite-version-unreadable",
            "detail": f"{tool} version probe did not report a numeric version: {output}",
        }
    if _version_key(observed) < _version_key(minimum):
        return {
            **result,
            "status": "outdated",
            "code": "pack-prerequisite-outdated",
            "observed_version": observed,
            "detail": (
                f"{tool} {observed} is installed; {minimum} or newer is required."
            ),
        }
    return {
        **result,
        "status": READY_STATUS,
        "code": "pack-prerequisite-ready",
        "observed_version": observed,
        "detail": f"{tool} {observed} satisfies minimum {minimum}.",
    }


def _install_recipe(recipes: Mapping[str, Any]) -> str:
    system = _SYSTEM().lower()
    if system in recipes:
        return str(recipes[system])
    return "; ".join(f"{name}: {recipes[name]}" for name in sorted(recipes))


def _observed_version(output: str) -> str | None:
    match = _VERSION.search(output)
    return match.group(1) if match else None


def _version_key(value: str) -> tuple[int, ...]:
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (4 - len(parts))


def _diagnostic(value: object) -> str:
    text = str(value or "").strip()
    printable = "".join(char if char.isprintable() else " " for char in text)
    return printable[:512] or "no diagnostic output"


__all__ = [
    "PROBE_TIMEOUT_SECONDS",
    "READY_STATUS",
    "collect_installed_pack_prerequisites",
    "probe_pack_prerequisites",
    "probe_prerequisites",
    "unsatisfied_prerequisites",
]

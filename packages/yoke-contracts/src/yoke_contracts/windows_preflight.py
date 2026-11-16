"""Pure native Windows machine facts to status-shaped verdicts.

No probe, write, doctor or engine dependency belongs here. Notices describe
coverage, never certify that an unexercised Windows edition is supported.
"""

from __future__ import annotations

from typing import Any, Mapping
import re


def issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    result = {"severity": severity, "code": code, "message": message}
    if hint:
        result["hint"] = hint
    return result


def verdicts(facts: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return named proceed (info), notice (warning), or refuse (error) rows."""
    if facts.get("system") != "Windows":
        return []
    rows = []

    def add(severity: str, code: str, message: str, hint: str = "") -> None:
        rows.append(issue(severity, "windows_" + code, message, hint))

    raw_build = str(facts.get("build") or "")
    build = int(raw_build) if raw_build.isdecimal() else 0
    edition = str(facts.get("edition") or "unknown")
    arch = str(facts.get("arch") or "unknown").lower()
    server = "server" in edition.lower()
    edition_unknown = (
        not server
        and build >= 22000
        and not re.search(r"\b(home|pro|enterprise)\b", edition, re.I)
    )
    if (
        edition_unknown
        or build < (17763 if server else 10240)
        or arch
        not in (
            "amd64",
            "x86_64",
            "arm64",
            "aarch64",
        )
    ):
        add(
            "error",
            "version",
            f"Unsupported Windows build {build}, {edition}, {arch}.",
            "Use Windows 11 Home/Pro/Enterprise, Windows 10 or Server 2019+, x64 or ARM64; runtime coverage remains untested.",
        )
    else:
        add(
            "warning",
            "coverage_untested",
            f"Windows {edition} build {build}, {arch}: runtime coverage untested.",
            "Keep the build and edition with test results; native support awaits integrated acceptance.",
        )
    add(
        "warning" if facts.get("elevated") else "info",
        "elevation",
        "Elevated shell: per-user files may become inaccessible to normal sessions."
        if facts.get("elevated")
        else "Standard user: per-user setup needs no elevation.",
        "Run setup from a normal shell; keep the install per-user.",
    )
    for entry in facts.get("storage", ()):
        path = entry["path"]
        unsafe = entry.get("kind") in ("onedrive", "network", "roaming")
        fs = str(entry.get("filesystem") or "unknown").upper()
        if unsafe or fs in ("EXFAT", "FAT", "FAT32"):
            add(
                "error",
                "private_storage",
                f"Secrets/database path {path}: {entry.get('kind')}, {fs} cannot provide local owner-only storage.",
                "Choose a local NTFS path outside OneDrive, roaming profiles and network shares.",
            )
        elif fs == "UNKNOWN":
            add(
                "error",
                "storage_unknown",
                f"Cannot verify owner-only storage at {path}.",
                "Check drive access and use a local NTFS path, then rerun setup.",
            )
        else:
            add("info", "private_storage", f"Local {fs} storage: {path}.")
    repo = str(facts.get("repo") or "")
    if repo.lower().startswith(("\\\\wsl$\\", "\\\\wsl.localhost\\")):
        add(
            "error",
            "wsl_repository",
            f"Repository belongs to WSL: {repo}.",
            "Run Yoke inside that WSL distribution, or move the checkout to a native Windows drive.",
        )
    if not facts.get("long_paths_enabled") and facts.get("longest_path", 0) >= 260:
        add(
            "error",
            "long_paths",
            f"Path length {facts['longest_path']} reaches the Windows limit with LongPathsEnabled off.",
            "Move the checkout to a shorter local path or ask IT to enable Win32 long paths; restart the shell.",
        )
    else:
        add("info", "long_paths", "Paths fit the current Windows long-path setting.")
    for name in facts.get("invalid_names", ()):
        add(
            "error",
            "reserved_name",
            f"Reserved Windows name: {name}.",
            "Rename this file or branch from its owning OS before native setup.",
        )
    for names in facts.get("colliding_names", ()):
        add(
            "error",
            "case_collision",
            f"Case-colliding names: {', '.join(names)}.",
            "Rename the colliding files or branches before native setup.",
        )
    for tool, command in (
        ("git", "winget install --id Git.Git -e"),
        ("ssh", "Ask IT to enable the Windows OpenSSH Client optional feature."),
    ):
        add(
            "info" if facts.get(tool) else "warning",
            tool,
            f"{tool}: {facts.get(tool) or 'not found; repository/SSH operations are unavailable'}.",
            f"Install step: {command}",
        )
    if facts.get("wsl_yoke"):
        add(
            "warning",
            "wsl_install",
            "Yoke also exists inside WSL; Windows and WSL have separate homes and machine identities.",
            "Use Windows Yoke for native drive checkouts and WSL Yoke for Linux checkouts; do not share secret/database homes.",
        )
    if not facts.get("desktop") or not facts.get("browser"):
        add(
            "warning",
            "code_flow",
            "No desktop or default browser is available.",
            "Use the URL and code printed by `yoke connect` on another browser-equipped device.",
        )
    if facts.get("store_blocked"):
        add(
            "warning",
            "store_blocked",
            "Microsoft Store is blocked; Store harness installs are unavailable.",
            "Use each harness's native direct installer or ask IT for an approved package.",
        )
    for host in facts.get("blocked_hosts", ()):
        add(
            "warning",
            "download_host",
            f"Required download host is unreachable: {host}.",
            "Ask IT to permit this host through the configured proxy/firewall, then rerun setup.",
        )
    for evidence in facts.get("policy_blocks", ()):
        policy = evidence["policy"]
        add(
            "error",
            "application_control",
            f"{policy} blocked {evidence['file']}: {evidence['evidence']}.",
            "Give IT this file path and policy evidence for review. If Smart App Control blocked it, ask the publisher for a signed build; it has no per-app exception.",
        )
    for error in facts.get("probe_errors", ()):
        add(
            "warning",
            "probe_incomplete",
            f"Preflight fact unavailable: {error}.",
            "Ask IT to make this read-only probe available, then rerun `yoke status`; absence of evidence is not a pass.",
        )
    return rows

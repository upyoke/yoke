"""Read-only, stdlib Windows fact collection; safe to import on every OS."""

from __future__ import annotations

import ctypes
import json
import ntpath
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

DOWNLOAD_HOSTS = ("claude.ai", "downloads.cursor.com", "registry.npmjs.org")
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)


def _command_text(argv: list[str], raw: bytes) -> str:
    encoding = (
        "utf-16-le"
        if argv[0] in ("wsl.exe", "wevtutil.exe") and b"\0" in raw
        else "utf-8-sig"
    )
    return raw.decode(encoding, errors="replace").lstrip("\ufeff")


def _run(argv: list[str], errors: list[str]) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, timeout=4)
        if result.returncode:
            reason = _command_text(argv, result.stderr).strip()[:240]
            errors.append(f"{argv[0]} exited {result.returncode}: {reason}")
            return ""
        return _command_text(argv, result.stdout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"{argv[0]}: {type(exc).__name__}")
        return ""


def _registry(root, key: str, name: str, errors: list[str], default=None):
    import winreg

    try:
        with winreg.OpenKey(root, key) as opened:
            return winreg.QueryValueEx(opened, name)[0]
    except FileNotFoundError:
        return default
    except OSError as exc:
        errors.append(f"registry {key}/{name}: {type(exc).__name__}")
        return default


def _storage(path: str, environ, errors: list[str]) -> dict:
    resolved = os.path.realpath(path)
    if resolved.startswith("\\\\?\\UNC\\"):
        resolved = "\\\\" + resolved[8:]
    elif resolved.startswith("\\\\?\\"):
        resolved = resolved[4:]
    kind = "local"
    if resolved.startswith("\\\\"):
        kind = "network"
    for key in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer", "APPDATA"):
        base = environ.get(key)
        if base:
            base = ntpath.normpath(base)
        if (
            base
            and ntpath.splitdrive(base)[0].lower()
            == ntpath.splitdrive(resolved)[0].lower()
            and ntpath.commonpath((base, resolved)).lower() == base.lower()
        ):
            kind = "roaming" if key == "APPDATA" else "onedrive"
    root = ntpath.splitdrive(resolved)[0] + "\\"
    if ctypes.windll.kernel32.GetDriveTypeW(root) == 4:
        kind = "network"
    fs = ctypes.create_unicode_buffer(64)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        root, None, 0, None, None, None, fs, len(fs)
    )
    if not ok:
        errors.append(f"GetVolumeInformationW failed for {root}")
    return {"path": path, "kind": kind, "filesystem": fs.value or "unknown"}


def name_facts(names: list[str]) -> tuple[list[str], list[list[str]]]:
    """Check Git paths and refs, including names Windows cannot materialize."""
    invalid, groups = [], {}
    for name in names:
        parts = name.replace("\\", "/").split("/")
        if any(
            RESERVED.match(p)
            or p.endswith((".", " "))
            or any(c in p for c in '<>:"|?*')
            for p in parts
        ):
            invalid.append(name)
        # Each parent component can collide too (Foo/a versus foo/b).
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            groups.setdefault(prefix.casefold(), set()).add(prefix)
    return invalid, [sorted(group) for group in groups.values() if len(group) > 1]


def _policy_blocks(errors: list[str]) -> list[dict[str, str]]:
    blocks = []
    for log, ids, policy in (
        ("Microsoft-Windows-AppLocker/EXE and DLL", "EventID=8004", "AppLocker"),
        (
            "Microsoft-Windows-CodeIntegrity/Operational",
            "EventID=3077",
            "WDAC / Smart App Control",
        ),
    ):
        raw = _run(
            [
                "wevtutil.exe",
                "qe",
                log,
                f"/q:*[System[({ids}) and TimeCreated[timediff(@SystemTime) <= 86400000]]]",
                "/c:20",
                "/rd:true",
                "/f:xml",
                "/uni:true",
            ],
            errors,
        )
        if not raw.strip():
            continue
        try:
            root = ET.fromstring("<Events>" + raw + "</Events>")
            if not len(root) and (root.text or "").strip():
                raise ValueError("event log contains text instead of events")
            for event in root:
                data = {
                    (
                        node.attrib.get("Name") or node.tag.rsplit("}", 1)[-1]
                    ).lower(): node.text or ""
                    for node in event.iter()
                    if not len(node)
                }
                file = data.get("filename") or data.get("filepath")
                if not file:
                    errors.append(
                        f"{log}: enforced block record {data.get('eventrecordid', 'unknown')} has no file field; inspect it in Event Viewer"
                    )
                    continue
                if any(
                    name in file.lower()
                    for name in ("yoke", "python", "uv.exe", "postgres")
                ):
                    blocks.append(
                        {
                            "policy": policy,
                            "file": file,
                            "evidence": f"{log}: enforced block event {data.get('eventid', 'unknown')}, record {data.get('eventrecordid', 'unknown')}; policy {data.get('policyname') or data.get('rulename') or 'see Event Viewer'}",
                        }
                    )
        except (ET.ParseError, ValueError):
            errors.append(f"unreadable policy events: {log}")
    return blocks


def collect_facts(
    *, home: str | Path | None = None, repo: str | Path | None = None
) -> dict:
    system = platform.system()
    if system != "Windows":
        return {"system": system}
    import winreg

    errors: list[str] = []
    env = os.environ
    selected_home = str(home or env.get("YOKE_HOME") or Path.home() / ".yoke")
    selected_repo = str(repo or Path.cwd())
    current = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    build = _registry(
        winreg.HKEY_LOCAL_MACHINE, current, "CurrentBuildNumber", errors, "0"
    )
    edition = _registry(
        winreg.HKEY_LOCAL_MACHINE, current, "ProductName", errors, "unknown"
    )
    long_paths = _registry(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\FileSystem",
        "LongPathsEnabled",
        errors,
        0,
    )
    git = shutil.which("git")
    names = []
    refs = ""
    if git and Path(selected_repo).is_dir():
        if (Path(selected_repo) / ".git").exists():
            names = (
                _run([git, "-C", selected_repo, "ls-files", "-z"], errors)
                .strip("\0")
                .split("\0")
            )
            refs = _run(
                [
                    git,
                    "-C",
                    selected_repo,
                    "for-each-ref",
                    "--format=%(refname:short)",
                    "refs/heads",
                ],
                errors,
            )
    invalid, collisions = name_facts([name for name in names if name])
    ref_invalid, ref_collisions = name_facts(refs.splitlines())
    invalid.extend("branch " + name for name in ref_invalid)
    collisions.extend(["branch " + name for name in group] for group in ref_collisions)
    blocked = []
    for host in DOWNLOAD_HOSTS:
        try:
            with urllib.request.urlopen(
                urllib.request.Request("https://" + host, method="HEAD"), timeout=2
            ):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 451):
                errors.append(
                    f"{host}: HTTP {exc.code}; confirm corporate policy or host access before installing"
                )
        except OSError as exc:
            blocked.append(f"{host} ({type(exc).__name__})")
    # Never start a distribution or mount its filesystem during preflight.
    wsl_yoke = False
    if shutil.which("wsl.exe"):
        distributions = _run(["wsl.exe", "--list", "--running", "--quiet"], errors)
        for distro in distributions.splitlines():
            if distro.strip():
                found = _run(
                    [
                        "wsl.exe",
                        "--distribution",
                        distro.strip(),
                        "--exec",
                        "/bin/sh",
                        "-c",
                        "command -v yoke || true",
                    ],
                    errors,
                )
                wsl_yoke = wsl_yoke or bool(found.strip())
        errors.append(
            "Stopped WSL distributions were not started or inspected. Check `command -v yoke` inside any distro you use; keep Windows and WSL homes and machine identities separate"
        )
    storage = []
    for path in (selected_home,):
        try:
            storage.append(_storage(path, env, errors))
        except (OSError, ValueError) as exc:
            errors.append(f"storage {path}: {type(exc).__name__}")
            storage.append({"path": path, "filesystem": "unknown"})
    browser = _registry(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        "ProgId",
        errors,
    )
    store = _registry(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Policies\Microsoft\WindowsStore",
        "RemoveWindowsStore",
        errors,
        0,
    )
    return {
        "system": system,
        "build": int(str(build)) if str(build).isdecimal() else 0,
        "edition": edition,
        "arch": platform.machine(),
        "elevated": bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "storage": storage,
        "repo": selected_repo,
        "long_paths_enabled": bool(long_paths),
        "longest_path": max(
            [len(selected_home + "/config.json"), len(selected_repo)]
            + [len(selected_repo) + len(n) + 1 for n in names]
        ),
        "invalid_names": invalid,
        "colliding_names": collisions,
        "git": git,
        "ssh": shutil.which("ssh"),
        "wsl_yoke": wsl_yoke,
        "desktop": env.get("SESSIONNAME", "").lower() not in ("", "services")
        and not env.get("SSH_CONNECTION"),
        "browser": bool(browser),
        "store_blocked": bool(store),
        "blocked_hosts": blocked,
        "policy_blocks": _policy_blocks(errors),
        "probe_errors": errors,
    }


if __name__ == "__main__":
    print(json.dumps(collect_facts(), indent=2))

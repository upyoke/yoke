"""CI-only real installation and two upgrades from a loopback distribution."""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from yoke_core.tools.build_release import build_release


def run(argv, *, env=None, cwd=None):
    result = subprocess.run(
        argv, env=env, cwd=cwd, text=True, capture_output=True, timeout=1200
    )
    if result.returncode:
        raise RuntimeError(
            f"installer_ci_failed: {argv}: {result.stdout}\n{result.stderr}; fix the installer and rerun this workflow."
        )
    return result.stdout.strip()


def status(argv, env, cwd):
    result = subprocess.run(
        argv, env=env, cwd=cwd, text=True, capture_output=True, timeout=120
    )
    payload = json.loads(result.stdout)
    unexpected = [
        row
        for row in payload.get("issues", [])
        if row.get("severity") == "error"
        and row.get("code")
        not in {
            "config_missing",
            "connections_required",
            "active_env_required",
            "active_env",
            "schema_version",
        }
    ]
    if unexpected or not payload.get("runtime", {}).get("package_versions", {}).get(
        "yoke-cli"
    ):
        raise RuntimeError(
            f"installer_ci_status_failed: {argv}: {payload}; repair the installed product and rerun."
        )
    print(
        f"Proved {argv}: {payload['runtime']['package_versions']['yoke-cli']}",
        flush=True,
    )


def prove(root: Path):
    checkout = Path(__file__).resolve().parents[3]
    source = root / "source"
    run(["git", "clone", "--shared", str(checkout), str(source)])
    publication = root / "public"
    publication.mkdir()
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(publication))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    origin = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    home = root / "home"
    home.mkdir()
    bindir = home / ".local/bin"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("YOKE_", "UV_TOOL_", "XDG_"))
    }
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        YOKE_MACHINE_HOME=str(home / ".yoke"),
        UV_TOOL_DIR=str(home / "tools"),
        UV_TOOL_BIN_DIR=str(bindir),
        YOKE_INSTALL_BASE_URL=origin,
        YOKE_INSTALL_YES="1",
        YOKE_NO_SETUP="1",
        PATH=str(bindir) + os.pathsep + os.environ["PATH"],
    )
    # Keep CI's user registry intact; the installer/doctor still exercise the
    # real registry during the proof, then restore its exact value and type.
    old_path = None
    if sys.platform == "win32":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                old_path = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                pass
    try:
        for number in range(3):
            # Disposable clone commits yield three real commit-clock versions.
            clock = (datetime.now(timezone.utc) + timedelta(minutes=number)).isoformat()
            commit_env = dict(
                os.environ, GIT_AUTHOR_DATE=clock, GIT_COMMITTER_DATE=clock
            )
            run(
                [
                    "git",
                    "-c",
                    "user.name=Installer CI",
                    "-c",
                    "user.email=installer@example.invalid",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "Installer fixture release",
                ],
                env=commit_env,
                cwd=source,
            )
            sha = run(["git", "rev-parse", "HEAD"], cwd=source)
            build = build_release(
                repo_root=source,
                output_root=root / f"release-{number}",
                base_url=origin,
                source_commit=sha,
                channel="stable",
            )
            shutil.copytree(build.paths.output_root, publication, dirs_exist_ok=True)
            yoke = str(bindir / ("yoke.cmd" if sys.platform == "win32" else "yoke"))
            if number == 0:
                if sys.platform == "win32":
                    run(
                        [
                            "powershell.exe",
                            "-NoProfile",
                            "-File",
                            str(publication / "install.ps1"),
                            "--no-setup",
                        ],
                        env=env,
                        cwd=home,
                    )
                else:
                    run(
                        ["sh", str(publication / "install"), "--yes", "--no-setup"],
                        env=env,
                        cwd=home,
                    )
            else:
                run([yoke, "update", "--json"], env=env, cwd=home)
            assert run([yoke, "--version"], env=env, cwd=home) == build.version
            if sys.platform == "win32":
                status(
                    ["powershell.exe", "-NoProfile", "-Command", "yoke status --json"],
                    env,
                    home,
                )
                status(["cmd.exe", "/d", "/c", "yoke status --json"], env, home)
                bash = Path(os.environ["ProgramFiles"]) / "Git/bin/bash.exe"
                status(
                    [str(bash), "--noprofile", "--norc", "-c", "yoke status --json"],
                    env,
                    home,
                )
            else:
                status([yoke, "status", "--json"], env, home)
    finally:
        yoke = bindir / ("yoke.cmd" if sys.platform == "win32" else "yoke")
        if yoke.exists():
            run([str(yoke), "hook", "resident", "stop"], env=env, cwd=home)
        server.shutdown()
        server.server_close()
        thread.join()
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
            ) as key:
                if old_path is None:
                    try:
                        winreg.DeleteValue(key, "Path")
                    except FileNotFoundError:
                        pass
                else:
                    winreg.SetValueEx(key, "Path", 0, old_path[1], old_path[0])


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="yoke-installer-proof-", dir=os.environ.get("RUNNER_TEMP")) as directory:
        prove(Path(directory))

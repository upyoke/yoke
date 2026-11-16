"""Disposable Linux account whose real HOME owns the smoke user manager."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ACCOUNT_HOME = "YOKE_SMOKE_LINUX_ACCOUNT_HOME"
SUDOERS_ROOT = Path("/etc/sudoers.d")


def verified_account_environment() -> tuple[Path, dict[str, str]]:
    """Require a real login home, reachable user manager and logout cleanup."""
    import pwd

    home = Path(os.environ[ACCOUNT_HOME]).resolve()
    uid = os.getuid()
    runtime = f"/run/user/{uid}"
    bus = f"unix:path={runtime}/bus"
    if uid == 0 or Path(pwd.getpwuid(uid).pw_dir).resolve() != home:
        raise RuntimeError("smoke_account_home_mismatch: use the disposable account launcher")
    if os.environ.get("XDG_RUNTIME_DIR") != runtime or os.environ.get("DBUS_SESSION_BUS_ADDRESS") != bus:
        raise RuntimeError("smoke_account_bus_mismatch: use this account's user manager")
    service_env = {"XDG_RUNTIME_DIR": runtime, "DBUS_SESSION_BUS_ADDRESS": bus}
    subprocess.run(["systemctl", "--user", "show-environment"], check=True, capture_output=True)
    linger = subprocess.run(
        ["loginctl", "show-user", str(uid), "--property=Linger", "--value"],
        check=True, capture_output=True, text=True,
    )
    if linger.stdout.strip() != "no":
        raise RuntimeError("smoke_account_linger_enabled: the disposable account must stop at logout")
    return home, service_env


def run_account(root: Path, output: Path, uv: Path, expected_os: str, architecture: str) -> int:
    """Open a PAM login session; leave the runner account and its manager alone."""
    if sys.platform != "linux" or os.getuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("smoke_account_requires_disposable_linux_runner: invoke from Linux product-smoke CI")
    user = f"yksmoke{os.getpid()}"
    original = root.stat()
    created = False
    uid = None
    policy = None
    with tempfile.TemporaryDirectory(prefix="yoke-smoke-account-", dir="/home") as scratch:
        home = Path(scratch) / "home"
        home.mkdir()
        try:
            subprocess.run([
                "useradd", "--no-log-init", "--no-create-home", "--home-dir", str(home),
                "--shell", "/bin/bash", user,
            ], check=True)
            created = True
            import pwd

            uid = pwd.getpwnam(user).pw_uid
            # Match the disposable runner's unattended browser-package authority.
            policy = SUDOERS_ROOT / f"yoke-smoke-{uid}"
            policy.write_text(f"{user} ALL=(ALL) NOPASSWD: ALL\n", encoding="utf-8")
            policy.chmod(0o440)
            subprocess.run(["visudo", "-cf", str(policy)], check=True)
            subprocess.run(["chown", "-R", user, scratch, str(root)], check=True)
            runtime = f"/run/user/{uid}"
            # PAM registers the account with logind and starts its user manager
            # before exec. Linger is never enabled; the unit owns this login.
            result = subprocess.run([
                "systemd-run", "--wait", "--pipe", "--collect", f"--unit=yoke-smoke-{uid}",
                f"--uid={user}", "--property=PAMName=login", f"--working-directory={root}",
                "/usr/bin/env", "-i", f"HOME={home}", f"{ACCOUNT_HOME}={home}",
                f"XDG_RUNTIME_DIR={runtime}", f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
                f"PATH={uv.parent}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}{os.defpath}",
                f"SMOKE_EXPECTED_OS={expected_os}", f"SMOKE_EXPECTED_ARCHITECTURE={architecture}",
                sys.executable, str(root / "runtime/api/tools/product_runner_smoke.py"),
                "--output", str(output),
            ], check=False)
            return result.returncode
        finally:
            if created:
                # Product smoke uninstalls relay before its login exits. Stop
                # any failed-session residue before deleting the account/home.
                subprocess.run(["loginctl", "terminate-user", user], check=False)
                if uid is not None:
                    subprocess.run(["systemctl", "stop", f"user@{uid}.service"], check=False)
                if policy is not None:
                    policy.unlink(missing_ok=True)
                subprocess.run(["userdel", user], check=True)
                subprocess.run(["chown", "-R", f"{original.st_uid}:{original.st_gid}", str(root)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--expected-os", required=True)
    parser.add_argument("--expected-architecture", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    return run_account(root, args.output.resolve(), args.uv.resolve(), args.expected_os, args.expected_architecture)


if __name__ == "__main__":
    raise SystemExit(main())

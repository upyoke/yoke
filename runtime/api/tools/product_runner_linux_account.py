"""Disposable Linux account whose real HOME owns the smoke's systemd user manager.

Linux relay setup installs a user unit under ``~/.config/systemd/user`` and
needs that account's own user manager. ``product-smoke.yml`` therefore runs the
whole smoke, as root, through :func:`run_account`: it creates a throwaway
account, copies the checkout into the account's home, and opens a real PAM
login session (``systemd-run -p PAMName=login``, Linger=no). Inside it,
``product_runner_smoke`` sees :data:`ACCOUNT_HOME` and calls
:func:`verified_account_environment`.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ACCOUNT_HOME = "YOKE_SMOKE_LINUX_ACCOUNT_HOME"
SUDOERS_ROOT = Path("/etc/sudoers.d")
RELAUNCH = "rerun the product-smoke workflow, which starts the smoke through product_runner_linux_account.py"


class AccountRefused(RuntimeError):
    """The disposable account or its login session is not what the smoke needs."""


def _probe(argv: list[str], reason: str) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AccountRefused(
            f"{reason}: `{' '.join(argv)}` exited {result.returncode}: "
            f"{result.stderr.strip()}; {RELAUNCH}"
        )
    return result.stdout.strip()


def verified_account_environment() -> tuple[Path, dict[str, str]]:
    """Require the passwd home, the PAM session's user bus, and logout cleanup."""
    import pwd

    home = Path(os.environ[ACCOUNT_HOME]).resolve()
    uid = os.getuid()
    runtime = f"/run/user/{uid}"
    bus = f"unix:path={runtime}/bus"
    if uid == 0 or Path(pwd.getpwuid(uid).pw_dir).resolve() != home:
        raise AccountRefused(
            f"smoke_account_home_mismatch: uid {uid} home is not {home}; {RELAUNCH}"
        )
    session = {
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR"),
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    }
    if session != {"XDG_RUNTIME_DIR": runtime, "DBUS_SESSION_BUS_ADDRESS": bus}:
        raise AccountRefused(
            f"smoke_account_bus_mismatch: the PAM login set {session}, expected {runtime} "
            f"and {bus}; {RELAUNCH}"
        )
    _probe(["systemctl", "--user", "show-environment"], "smoke_account_user_manager_unavailable")
    linger = _probe(
        ["loginctl", "show-user", str(uid), "--property=Linger", "--value"],
        "smoke_account_linger_unknown",
    )
    if linger != "no":
        raise AccountRefused(
            f"smoke_account_linger_enabled: Linger={linger!r}; the disposable account "
            f"must stop at logout, so never enable linger for it; {RELAUNCH}"
        )
    return home, session


def run_account(root: Path, output: Path, uv: Path, expected_os: str, architecture: str) -> int:
    """Run the smoke inside a PAM login; leave the runner account and its manager alone."""
    if sys.platform != "linux" or os.getuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true":
        raise AccountRefused(
            "smoke_account_requires_disposable_linux_runner: this launcher creates and "
            "deletes an OS account; run it only from the Linux product-smoke CI job"
        )
    runner = output.parent.stat()
    user = f"yksmoke{os.getpid()}"
    created = False
    uid = None
    policy = None
    with tempfile.TemporaryDirectory(prefix="yoke-smoke-account-", dir="/home") as scratch:
        home = Path(scratch) / "home"
        checkout = home / "checkout"
        evidence = home / "product-smoke-evidence"
        try:
            subprocess.run([
                "useradd", "--no-log-init", "--no-create-home", "--home-dir", str(home),
                "--shell", "/bin/bash", user,
            ], check=True)  # fmt: skip
            created = True
            import pwd

            uid = pwd.getpwnam(user).pw_uid
            # Match the disposable runner's unattended browser-package authority.
            policy = SUDOERS_ROOT / f"yoke-smoke-{uid}"
            policy.write_text(f"{user} ALL=(ALL) NOPASSWD: ALL\n", encoding="utf-8")
            policy.chmod(0o440)
            subprocess.run(["visudo", "-cf", str(policy)], check=True)
            # The account owns its own copy; the runner checkout stays untouched.
            home.mkdir()
            shutil.copytree(root, checkout, symlinks=True)
            subprocess.run(["chown", "-R", f"{user}:", scratch], check=True)
            # PAM registers the session with logind and starts the user manager,
            # which supplies XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS. A
            # systemd service inherits nothing else from this root process.
            result = subprocess.run([
                "systemd-run", "--wait", "--pipe", "--collect", "--quiet",
                f"--unit=yoke-smoke-{uid}", f"--uid={user}", "--property=PAMName=login",
                f"--working-directory={checkout}",
                f"--setenv={ACCOUNT_HOME}={home}",
                f"--setenv=SMOKE_EXPECTED_OS={expected_os}",
                f"--setenv=SMOKE_EXPECTED_ARCHITECTURE={architecture}",
                # pam_env replaces any --setenv PATH from /etc/environment, so
                # set the tool path after PAM has run.
                "/usr/bin/env",
                f"PATH={uv.parent}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}{os.defpath}",
                sys.executable, str(checkout / "runtime/api/tools/product_runner_smoke.py"),
                "--output", str(evidence),
            ], check=False)  # fmt: skip
            return result.returncode
        finally:
            if evidence.is_dir():
                # Hand the proof back to the runner account for upload.
                shutil.copytree(evidence, output, dirs_exist_ok=True)
                subprocess.run(["chown", "-R", f"{runner.st_uid}:{runner.st_gid}", str(output)], check=True)
            if created:
                # The smoke uninstalls its relay before its login exits. Stop
                # any failed-session residue before deleting the account.
                subprocess.run(["loginctl", "terminate-user", user], check=False)
                if uid is not None:
                    subprocess.run(["systemctl", "stop", f"user@{uid}.service"], check=False)
                if policy is not None:
                    policy.unlink(missing_ok=True)
                subprocess.run(["userdel", user], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--expected-os", required=True)
    parser.add_argument("--expected-architecture", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        return run_account(
            root, args.output.resolve(), args.uv.resolve(),
            args.expected_os, args.expected_architecture,
        )  # fmt: skip
    except AccountRefused as exc:
        print(f"product-smoke failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

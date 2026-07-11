"""Materialize self-host secrets, drop root, and exec the normal server."""

from __future__ import annotations

import os
from pathlib import Path
import pwd
import sys
from yoke_core.tools.self_host_secret_materialization import (
    SELF_HOST_RUNTIME_SECRETS_DIR,
    SELF_HOST_SOURCE_SECRETS_DIR,
    SelfHostServerBootstrapError,
    materialize_self_host_runtime_secrets,
)


SELF_HOST_RUNTIME_USER = "yoke"


def drop_to_self_host_runtime_identity(*, uid: int, gid: int) -> None:
    """Clear supplementary authority and irreversibly become the runtime user."""
    if os.geteuid() != 0:
        raise SelfHostServerBootstrapError(
            "self-host server bootstrap must start as container root"
        )
    os.setgroups([])
    if hasattr(os, "setresgid"):
        os.setresgid(gid, gid, gid)
    else:
        os.setgid(gid)
    if hasattr(os, "setresuid"):
        os.setresuid(uid, uid, uid)
    else:
        os.setuid(uid)
    if os.geteuid() != uid or os.getegid() != gid or os.getgroups():
        raise SelfHostServerBootstrapError(
            "self-host server bootstrap did not drop all root authority"
        )


def assert_runtime_secrets_readable(paths: tuple[Path, ...]) -> None:
    """Prove the post-drop identity can open every materialized secret."""
    for path in paths:
        descriptor = -1
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            if not os.read(descriptor, 1):
                raise SelfHostServerBootstrapError(
                    f"materialized self-host secret is empty: {path.name}"
                )
        except OSError as exc:
            raise SelfHostServerBootstrapError(
                f"runtime identity cannot read self-host secret: {path.name}"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def assert_no_effective_linux_capabilities(
    *,
    status_path: Path = Path("/proc/self/status"),
) -> None:
    """Prove a Linux privilege drop cleared every effective capability."""
    if not status_path.exists():
        if sys.platform.startswith("linux"):
            raise SelfHostServerBootstrapError(
                "runtime capability state cannot be inspected"
            )
        return
    try:
        lines = status_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SelfHostServerBootstrapError(
            "runtime capability state cannot be inspected"
        ) from exc
    cap_eff = next(
        (
            line.partition(":")[2].strip()
            for line in lines
            if line.startswith("CapEff:")
        ),
        "",
    )
    try:
        effective = int(cap_eff, 16)
    except ValueError as exc:
        raise SelfHostServerBootstrapError(
            "runtime effective capability state is invalid"
        ) from exc
    if effective:
        raise SelfHostServerBootstrapError(
            "runtime identity retained effective Linux capabilities"
        )


def main(argv: list[str] | None = None) -> int:
    selected_args = list(sys.argv[1:] if argv is None else argv)
    if selected_args == ["--healthcheck"]:
        return _run_healthcheck_as_runtime_user()
    if selected_args:
        print(
            "self-host server bootstrap received unsupported arguments", file=sys.stderr
        )
        return 2
    try:
        if os.geteuid() != 0:
            raise SelfHostServerBootstrapError(
                "self-host server bootstrap must start as container root"
            )
        account = pwd.getpwnam(SELF_HOST_RUNTIME_USER)
        env, targets = materialize_self_host_runtime_secrets(
            os.environ,
            runtime_uid=account.pw_uid,
            runtime_gid=account.pw_gid,
            require_read_only_sources=True,
        )
        drop_to_self_host_runtime_identity(uid=account.pw_uid, gid=account.pw_gid)
        assert_runtime_secrets_readable(targets)
        assert_no_effective_linux_capabilities()
    except Exception as exc:  # noqa: BLE001 - fail closed before server exec
        print(f"self-host server bootstrap failed: {exc}", file=sys.stderr)
        return 1
    os.execvpe(
        sys.executable,
        [sys.executable, "-m", "yoke_core.api.server_entrypoint"],
        env,
    )
    return 1


def _run_healthcheck_as_runtime_user() -> int:
    """Drop the Compose user override before running the image healthcheck."""
    try:
        if os.geteuid() != 0:
            raise SelfHostServerBootstrapError(
                "self-host healthcheck bootstrap must start as container root"
            )
        account = pwd.getpwnam(SELF_HOST_RUNTIME_USER)
        drop_to_self_host_runtime_identity(uid=account.pw_uid, gid=account.pw_gid)
        assert_no_effective_linux_capabilities()
    except Exception as exc:  # noqa: BLE001 - detail is local container state
        print(f"self-host healthcheck bootstrap failed: {exc}", file=sys.stderr)
        return 1
    from yoke_core.api.container_healthcheck import main as healthcheck_main

    return healthcheck_main()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SELF_HOST_RUNTIME_SECRETS_DIR",
    "SELF_HOST_SOURCE_SECRETS_DIR",
    "SelfHostServerBootstrapError",
    "assert_no_effective_linux_capabilities",
    "assert_runtime_secrets_readable",
    "drop_to_self_host_runtime_identity",
    "main",
    "materialize_self_host_runtime_secrets",
]

"""Name a missing systemd user manager and the recovery that restores it."""

USER_MANAGER_UNAVAILABLE = "linux_yoke_service_manager_unavailable"
USER_MANAGER_PROBE = ("systemctl", "--user", "show-environment")


def user_manager_unavailable(stderr, *, wsl, distro, retry="retry"):
    """Build the refusal facts; remote Linux programs embed this source, so it stays import-free.

    A WSL distro's user manager lives in its session-1 login, and SSH through
    ``wsl.exe -e`` opens no login session, so only a fresh distro start restores it.
    """
    if wsl:
        recovery = (
            "This WSL distro's systemd user manager comes from its session-1 login, "
            "which has ended. From Windows run `wsl.exe --terminate "
            + (distro or "<distro>")
            + "`, then "
            + retry
            + "; the distro's next start opens session 1 again. Never enable linger."
        )
    else:
        recovery = (
            "Log in through a PAM session with a systemd user manager, then "
            + retry
            + "."
        )
    return {"user_manager_stderr": stderr.strip(), "recovery": recovery}

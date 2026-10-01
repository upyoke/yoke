# Linux relay supervision

Onboarding installs and enables a systemd user service for the selected
connection. A hosted connection runs its pinned served release; a local
universe runs this machine's installed Yoke. Both reuse the same relay state,
configuration, logs, and native harness inventory as macOS.

Before installing the relay, onboarding checks Python's `venv` and `ensurepip`
support during the existing Linux system-package setup. On Debian, Ubuntu and
WSL Ubuntu, it installs the matching `pythonX.Y-venv` package automatically,
using root, passwordless sudo, or the terminal's sudo prompt. The release
installer also checks the stable relay interpreter, including an existing
runtime whose Python version differs from the onboarding CLI. Missing package
authority or a failed installation stops setup with the package and recovery
named; no manual sudo command is required.

The unit lives at
`~/.config/systemd/user/com.upyoke.relay[.<environment-id>].service`.
It starts at login, restarts on failure, and stops after the last login session
logs out. Yoke does not enable linger. If linger is already enabled, installation
refuses with `relay_linger_enabled`; disable it for the user with
`loginctl disable-linger`, then retry `yoke relay install`.

Use `yoke relay status` to read the unit, login enablement, active state,
logout behavior, and relay health. `yoke relay install` repairs the unit using
the existing launcher and release installer; `yoke relay uninstall` disables
and removes it. Logs stay in the selected relay's state directory.

Doctor checks the current unit, whether it is enabled and active, the connected
heartbeat, and authorization. Without systemd as PID 1 (including containers
or WSL configured without systemd), it reports that the relay is not supervised
and why. Enable systemd in WSL or use a systemd Linux host. If the user manager
is unavailable, log in through a PAM session that starts it and retry.

The login lifetime follows systemd's user manager and the host's logout delay;
closing one shell while other sessions remain does not stop the relay.
[systemd service documentation](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml)
and [loginctl documentation](https://github.com/systemd/systemd/blob/main/man/loginctl.xml)
describe restart and linger behavior.

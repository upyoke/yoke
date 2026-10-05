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

Browser setup uses the same OS authority to provision Chromium's sandbox on
hosts enforcing `kernel.apparmor_restrict_unprivileged_userns` (including
Ubuntu 23.10+). It installs and loads an AppArmor `userns` allowance attached
only to Yoke's current Chromium and headless-shell executable paths. Updates
replace those attachments when Playwright changes its browser paths.
Authorization and browser QA invoke this setup before launching Chromium.
The sign-in window and browser QA run with Chromium's sandbox enabled; the
host restriction stays enabled. Missing system authority or AppArmor tooling,
or a profile that cannot load, stops browser setup with
`browser_apparmor_setup_failed` and the recovery step. Retry
`yoke qa browser setup` in a terminal with sudo access after repairing the
named cause; Yoke handles the system command and password prompt itself.

Chromium setup, authorization, and browser QA share Yoke's cache at
`~/.yoke/playwright-cache/yoke`, regardless of `XDG_CACHE_HOME` or an inherited
`PLAYWRIGHT_BROWSERS_PATH`. Setup checks that it can create and write the cache
before running installation commands. `browser_cache_not_writable` names the
path to make writable by the current user; then retry `yoke qa browser setup`.
Failed npm or Chromium installs report labeled tails of both stdout and stderr
(up to 20 lines and 4000 characters each), so a warning cannot hide the download
error. Repair the reported network or permissions cause and retry the same command.

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

TERM interrupts the current poll or maintenance call and closes job admission.
The relay gives active settlements at most two seconds from the signal, below
Ubuntu's five-second user-manager logout stop budget. Blocked network workers do
not hold Python open at exit. Existing server leases, native process custody,
and pending report files remain available for reconciliation on the next login.
Release repinning uses its longer settlement window. Yoke changes neither
linger nor the host's systemd timeouts or logout policy.

Service operations wait for shutdown and startup.
A `relay_systemd_command_timeout` means the command did
not settle within its bounded wait; the systemd job may still be running.
Inspect `systemctl --user list-jobs` and the unit's `systemctl --user status`
before retrying the relay operation.

SSH commands on the graphical desktop have a command-scoped supervisor with
an inner deadline. Successful command exit preserves intentionally persistent
product daemons, such as the browser daemon, after their starter completes.
On timeout or SSH loss, the supervisor terminates that command's descendants,
including nested process sessions and children that ignore TERM.
An unsuccessful command also settles its remaining descendants.
A timeout is reported as settled only after remote termination is verified.
If completion cannot be verified or interrupted descendants remain alive, the operation
returns `linux_command_custody_unsettled` with its private remote custody path.
Keep that recovery handle and inspect it before retrying; a local SSH timeout
alone does not prove that remote work stopped.

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

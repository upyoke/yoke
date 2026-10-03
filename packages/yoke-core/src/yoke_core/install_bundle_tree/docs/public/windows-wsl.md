# Yoke on Windows (WSL)

On Windows, everything Yoke runs belongs inside Linux: use WSL2 with Ubuntu.
Native Windows execution and Windows-side desktop apps, including their WSL
reach-in modes, are unsupported.

## Install inside Ubuntu

Install WSL2 and Ubuntu using [Microsoft's WSL installation guide](https://learn.microsoft.com/windows/wsl/install).
Open Ubuntu and follow [Install](install.md):

```bash
curl -fsSL https://upyoke.com/install | sh
yoke onboard
```

Keep repositories in the Linux filesystem, for example `~/projects/my-app`.
Avoid `/mnt/c` and other Windows drive mounts: Linux file operations and
permissions work best when the checkout stays in Linux. Run your agent CLIs
(Claude Code, Codex, or Cursor CLI) from that Ubuntu checkout.

## systemd, idle shutdown, and the relay

The installer checks WSL's PID 1. When systemd is off, it enables
`[boot] systemd=true` in `/etc/wsl.conf` automatically, preserving other
settings. It uses root access, passwordless privilege elevation, or the OS
password prompt in an interactive terminal. There is no Yoke yes/no prompt
and no need to type a privilege command yourself. If the machine cannot grant
access, setup names the reason and asks you to rerun `yoke wsl setup` in an
Ubuntu terminal with administrator access.

Install and `yoke onboard` also converge the Windows user's
`%UserProfile%\.wslconfig` to `[general] instanceIdleTimeout=-1`, preserving
other settings and comments. This disables distro idle shutdown so the relay
and background work keep running after every WSL terminal closes. The setting
applies to all WSL2 distributions owned by that Windows user. It requires WSL
2.5.4 or newer; an older or unreadable version produces a named refusal with
instructions to run `wsl --update` from Windows and retry `yoke wsl setup`.
Windows interop and access to the Windows user profile must be available.
See [Microsoft's WSL configuration reference](https://learn.microsoft.com/windows/wsl/wsl-config)
and [the WSL 2.5.4 release notes](https://github.com/microsoft/WSL/releases/tag/2.5.4).

When setup reports a change or systemd needs a restart, save your work, run
`wsl --shutdown` from Windows PowerShell, then reopen Ubuntu. That command stops all running WSL distributions.
See [Microsoft's systemd guide](https://learn.microsoft.com/windows/wsl/systemd).
The relay runs only while you are logged in; it is not a Windows service.

`yoke doctor` warns about a checkout under `/mnt/<drive>` and WSL without
systemd as PID 1.

## Linux desktop apps through WSLg

Linux desktop apps launched inside WSL through
[WSLg](https://learn.microsoft.com/windows/wsl/tutorials/gui-apps) are expected
to work, but Yoke has not yet verified them on a Windows test machine.
This includes Claude's Linux `.deb` and Cursor's Linux `.deb` or AppImage.
[Claude's Linux desktop app](https://claude.com/download) is beta and supports
Ubuntu and Debian only. Keep the app, its agent, and its checkout inside Linux.
Use the Linux CLIs for the currently verified path.

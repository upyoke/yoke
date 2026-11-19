# Native Windows lab controller prerequisites

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows controller prerequisites
<!-- /yoke:breadcrumbs -->

Prepare the controller before continuing [native Windows host setup](windows-native-host-provisioning.md).

On a macOS controller, install Microsoft's **Windows App** before starting
VM setup. Microsoft provides a [standalone installer](https://learn.microsoft.com/windows-app/get-started-connect-devices-desktops-apps?pivots=remote-pc)
or Mac App Store download; Homebrew's `windows-app` cask uses the vendor PKG.
The PKG requires controller administrator authentication. Complete installation
and verify Computer Use can select the packaged app before powering on the VM;
an unbundled SDL FreeRDP process may connect without a controllable app surface.
Use the verified private tailnet address, retain certificate validation, and
keep test-account credentials in private custody. Do not save credentials or
accept an unexpected certificate warning as part of unattended setup.

For a person viewing the lab, also install FreeRDP's visible SDL client on the
operator workstation (macOS: `brew install freerdp`; Linux: the distribution's
`freerdp-sdl` package). `yoke test-machine desktop-access --view` and
`yoke browser authorize --test-machine` open the native desktop in it and feed
the password on stdin; Windows App stays the Computer Use path above. Without
it they refuse `desktop_rdp_client_missing`. The lab needs nothing more: its
RDP listener, Remote Desktop Users membership and `YokeQa-ReturnToConsole`
task come from provisioning, and Yoke pins the direct route's certificate on
first use.

Require a controllable app window before starting VM setup. A
successful TCP connection or client process alone does not prove an interactive
desktop, successful authentication or completion of Windows first-run choices.
Prepare controller installation first. Once active setup starts, keep the lab
on until setup, sign-ins and QA finish; do not use countdowns or idle shutdowns.
Complete approved Windows privacy choices only after verifying the target
identity and private route. Finally deallocate, verify power state and report it.

Native Windows SSH and SFTP explicitly disable multiplexing on every controller,
including macOS and Linux. A local master can answer `ssh -O check` while its
session requests stall after VM power cycles; local master liveness does not
prove guest connectivity. Never replay a command after an ambiguous failure.

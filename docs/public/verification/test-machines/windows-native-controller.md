# Native Windows lab controller prerequisites

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows controller prerequisites
<!-- /yoke:breadcrumbs -->

Prepare the controller before continuing [native Windows host setup](windows-native-host-provisioning.md).

Agents drive the lab's desktop apps without any RDP client. QA walkers list,
focus, click, type into, press keys in and read any window with
`yoke qa mission desktop`, launch apps with `yoke qa mission host-command
--gui-session`, and see the result with `yoke test-machine screenshot`. All
three run in the auto-logged-on test user's console session through a Yoke
scheduled task, so the controller needs only Yoke and its SSH key; see
[driving desktop apps](windows-native-harnesses.md#driving-desktop-apps).

An RDP client is optional and only for people: watching the lab, or a
one-time sign-in handoff during setup. For that, install FreeRDP's visible SDL
client on the operator workstation (macOS: `brew install freerdp`; Linux: the
distribution's `freerdp-sdl` package). `yoke test-machine desktop-access
--view` and `yoke browser authorize --test-machine` open the native desktop in
it and feed the password on stdin. Without it they refuse
`desktop_rdp_client_missing`. Microsoft's **Windows App** also works for a
person who prefers it; it is not needed for agent input. The lab needs nothing
more: its RDP listener, Remote Desktop Users membership and
`YokeQa-ReturnToConsole` task come from provisioning, and Yoke pins the direct
route's certificate on first use. Use the verified private tailnet address,
retain certificate validation, and keep test-account credentials in private
custody.

A successful TCP connection or client process alone does not prove an
interactive desktop, successful authentication or completion of Windows
first-run choices; `yoke test-machine verify` and a screenshot do.
Prepare controller installation first. Once active setup starts, keep the lab
on until setup, sign-ins and QA finish; do not use countdowns or idle shutdowns.
Complete approved Windows privacy choices only after verifying the target
identity and private route. Finally deallocate, verify power state and report it.

Native Windows SSH and SFTP explicitly disable multiplexing on every controller,
including macOS and Linux. A local master can answer `ssh -O check` while its
session requests stall after VM power cycles; local master liveness does not
prove guest connectivity. Never replay a command after an ambiguous failure.

## Commit memory

Native Windows verification reports the system commit limit, committed bytes
and remaining commit headroom in the connection check. It fails below 1 GiB
of free commit memory. This is the headroom for new committed allocations.

If PowerShell fails to load or returns no host-facts object, Yoke retries that
read once. For `native_windows_host_resources_exhausted`, free memory or
enlarge the Windows page file, then rerun the command. A returned host-facts
object with invalid fields still reports `native_windows_host_facts_invalid`.

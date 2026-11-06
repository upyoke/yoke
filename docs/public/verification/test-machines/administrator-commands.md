# Administrator commands on Test Machines

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Administrator commands
<!-- /yoke:breadcrumbs -->

Run one setup command on a registered macOS or Linux machine:

```text
yoke test-machine exec --project P --test-machine NAME --admin -- COMMAND ARGS...
```

Read `yoke test-machine exec --help` before use. The executing workstation
uses its SSH agent and reads the machine-owned `desktop_password` secret.
That secret is the machine's administrator password, also used for desktop
access; the registered SSH user must be authorized to use sudo with it.
Import it from a private file, never put its value in a command or prompt:

```text
yoke projects capability secret set --project P --cap-type test-machine:NAME --key desktop_password --value-file PASSWORD_FILE
```

Product code sends the password through private stdin to `sudo -S`. The
password stays out of arguments, logs, events and artifacts; both output
streams and diagnostic tails redact it even across read boundaries. The
administrator command receives no stdin. Shell syntax after `--` follows
the ordinary remote `exec` contract. A foreign QA lease refuses access.

For Xcode and iOS Simulator setup on a Mac with Xcode installed:

```text
yoke test-machine exec --project P --test-machine NAME --admin -- xcodebuild -license accept
yoke test-machine exec --project P --test-machine NAME --admin -- xcodebuild -runFirstLaunch
yoke test-machine exec --project P --test-machine NAME --admin -- xcodebuild -downloadPlatform iOS
yoke test-machine exec --project P --test-machine NAME -- xcrun simctl list runtimes
```

A reset restores the home, which drops any simulator created after the
golden was captured, so a mission creates its own simulator each run. Pick
a device type from `xcrun simctl list devicetypes` and a runtime
from the list above; the command prints the new simulator's UDID:

```text
yoke test-machine exec --project P --test-machine NAME -- xcrun simctl create SIMULATOR_NAME DEVICE_TYPE RUNTIME
```

For Linux package setup, pass the host's package manager and its unattended
option through `--admin`. Windows administrator commands are unsupported
and refuse by name. A missing, unreadable or invalid credential names
`test-machine:NAME.desktop_password` and the import command above; repair
that stored credential before retrying. If sudo rejects authentication,
verify the registered user's administrator rights and the stored password.

These procedures ship with Yoke. Run `yoke project refresh` after upgrading
to receive the current documentation.

## Delete a registration

```text
yoke test-machine delete --project P --test-machine NAME --confirm
```

Project administrators can remove one registration, its settings, verification
status and operation receipts. QA waits, plan executions, runs and artifacts
remain unchanged. Active leases and waiting or reserved turns on the physical
host block deletion across all projects; finish or cancel that work first.
Reset debt also blocks deletion: run the named `yoke test-machine reset`
recovery before retrying. Deletion refuses if removing a reset receipt would
expose another project's reset debt.

After the server succeeds, the CLI removes this computer's project-scoped
`test-machine:NAME` secret directory. It keeps the shared `test-machine`
SSH key. Other computers keep their local credentials; remove those separately.
A local cleanup failure says the registration was deleted and names the
remaining directory. This command does not decommission the physical host.
A project may have no machines; `settings-replace --new` can register the same
name again. Generic `projects capability-settings remove` refuses test machines.

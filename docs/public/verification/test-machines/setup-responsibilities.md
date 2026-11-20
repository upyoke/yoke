# Setup responsibilities

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Setup responsibilities
<!-- /yoke:breadcrumbs -->

Keep [capability tags](host-provisioning.md#register-capability-tags) current
when registering or verifying a host, including after a sign-in changes.

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).

Agents do every step an agent physically can, including system settings such
as macOS permission prompts, opening harnesses through the desktop (native
Windows apps through `yoke qa mission desktop`, with no RDP client), choosing
permission modes, typing codes into wizards and approving machine-connect or
device codes in an already signed-in browser or with `yoke machines approve`.
The operator is needed only to enter their own password or credential, such as
a Google or GitHub password.
Machine passwords are entered only by product code from stored secrets, never typed by hand.

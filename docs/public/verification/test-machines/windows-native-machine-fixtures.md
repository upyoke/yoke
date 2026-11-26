# Native Windows machine-wide QA fixtures

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows machine-wide QA fixtures
<!-- /yoke:breadcrumbs -->

Start with [native Windows host provisioning](windows-native-host-provisioning.md),
which also creates the second local user these cells use.

## Fixtures and walker access

Exploratory walkers reach machine-wide Windows state through
`yoke qa mission host-command`, checked against the walk's lease:

- `--fixture NAME [--undo]` runs one idempotent fixture as SYSTEM through
  `az vm run-command invoke --command-id RunPowerShellScript` and prints its
  verify record: `grant-admin`, `system-proxy-root-ca` (a pinned, SHA-256
  checked mitmproxy on `127.0.0.1:18080` with its CA in `LocalMachine\Root`,
  WinHTTP and machine-wide WinINET), `applocker`, `task-scheduler-restricted`
  or `second-user`. A failure refuses `machine_fixture_failed` with the
  script's stderr and records.
- `--elevated` runs as the test user with its `grant-admin` token and refuses
  `native_windows_elevation_not_granted` without one. Without it, an admin
  token refuses `native_windows_test_user_required`, so a grant that was
  never undone fails every later command loudly.
- `--second-user` connects as `Zoë Tester` (`ssh -l`). That user has no
  console session, so `--second-user --gui-session` runs one S4U task; when
  Windows refuses it, the cell records the refusal.

Every native Windows reset first runs every undo, in one run-command, then
restores the profile and runs the probes. A failed undo fails the reset with
its verify records and leaves the lab `machine_needs_repair`.

The proxy fixture verifies trust by the thumbprint in its generated certificate
file. Undo verifies removal of that thumbprint before deleting the file. Undo
and the baseline probe detect the mitmproxy subject attributes in either order.
If a matching certificate has no ownership proof, undo reports its store and
thumbprint and leaves it in place. Establish ownership through an authorized
lab maintenance turn before changing that trust entry.

The `machine-baseline` standard probe fails with `probe_machine_drift`
when it finds AppLocker rules, WinHTTP or WinINET proxy settings, the fixture
CA, a mitmproxy process or port, files under `C:\YokeQa\fixtures`, the Task
Scheduler policy, an administrator test user, or a missing, disabled or
administrator second user. The recovery is a plain
`yoke test-machine reset`. The probe cannot read the second user's profile;
the `second-user` undo removes Yoke and uv from it as SYSTEM and fails with
its record if either remains.

## Rebuild in place (last resort)

When a reset still fails `probe_machine_drift` or the undo, there is no
OS-disk restore: goldens copy only the profile. Rebuild the VM's single
managed OS disk from its marketplace image; both disks exist only during the
swap, so nothing keeps billing:

```text
az vm deallocate --resource-group GROUP --name VM
az vm show --resource-group GROUP --name VM --query "{image:storageProfile.imageReference,disk:storageProfile.osDisk.managedDisk.id,location:location}" -o json
az disk create --resource-group GROUP --name VM-os-rebuild --location LOCATION --image-reference PUBLISHER:OFFER:SKU:VERSION
az vm update --resource-group GROUP --name VM --os-disk VM-os-rebuild
az vm start --resource-group GROUP --name VM
az disk delete --ids OLD_OS_DISK_ID --yes
```

Delete the old disk only after the new one boots and a
`RunPowerShellScript` invocation returns. Then rerun sections 2 to 4 of
[native Windows host provisioning](windows-native-host-provisioning.md). A person approves the Tailscale AuthURL and signs the harnesses back
in.

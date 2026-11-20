# Tailnet bootstrap

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Tailnet bootstrap
<!-- /yoke:breadcrumbs -->

One-time manual setup joins the controller and each cloud lab to the operator's
Tailscale tailnet before registering its MagicDNS host. The operator approves
each device sign-in; do not use an auth key or grant the standard SSH user
administrator membership to complete this setup.

## Start the lab and reach its current address

A stopped lab cannot install or join. Start it through the provider first:

```sh
aws ec2 start-instances --instance-ids INSTANCE_ID
aws ec2 wait instance-running --instance-ids INSTANCE_ID
aws ec2 describe-instances --instance-ids INSTANCE_ID --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
az vm start -g GROUP -n VM
az network public-ip show --ids IP_ID --query ipAddress -o tsv
```

Use the commands for the lab's provider. For the existing Azure labs, GROUP is
`yoke-test-machines`; a deallocated VM must start before Run Command works.
Before provider registration, follow the native guide's
[temporary public-IP lifecycle](windows-native-host-provisioning.md#tailscale-and-public-ip-lifetime).
Read the current IP after start; never reuse a previous EC2 address or register
that public address as the long-lived host.

Bootstrap SSH from the controller uses Yoke's Test Machine key store:

```sh
ssh -o UserKnownHostsFile=~/.yoke/test-machine/known_hosts -o HostKeyAlias=INSTANCE_ID USER@CURRENT_IP
```

INSTANCE_ID is the registered cloud resource ID (the full VM resource ID for
Azure). Verify a first or changed fingerprint before trusting it. Keep this
pin in Yoke's file, never the controller's `~/.ssh/known_hosts`.

## Join Linux with a stable name

Follow the [Linux installation procedure](https://tailscale.com/download/linux),
then enable the service and choose the lab name explicitly:

```sh
sudo systemctl enable --now tailscaled
sudo tailscale up --hostname=LAB_NAME
```

EC2's default `ip-172-...` hostname is not a useful stable lab identity. Use,
for example, `linux-lab`, and hand the displayed sign-in URL to the operator.
A headless join may wait for approval; inspect `tailscale status --json` rather
than treating an unapproved device as joined.

## Join Windows from the test desktop

Follow the [normal-user installation rule](index.md#install-as-the-test-user).
If the host is new, create the standard account and establish a private
desktop first. For native Windows, follow the
[bootstrap desktop route](windows-native-harnesses.md#first-tailscale-login-and-bootstrap-desktop).

Download the [Tailscale Windows installer](https://tailscale.com/download/windows)
in the standard user's Windows desktop session and accept its normal UAC
prompt for the machine service. Start Tailscale from that desktop and give the
operator the sign-in prompt for the intended tailnet and lab device. Install
Tailscale on the Windows side of a WSL fixture.

After sign-in, enable unattended operation and verify the service survives a
logout and reboot. The
[native Windows recovery guide](windows-native-provisioning-recovery.md#unattended-selection-before-registration)
describes the SYSTEM-context check for the already-installed service.

## Operator approval and registration

The operator opens each device's sign-in link, approves it in the intended
tailnet, then disables device key expiry in the Tailscale admin console.
Join the controller to that same tailnet and enable MagicDNS. Confirm the host's
service stays connected after logout/reboot before accepting unattended setup.

Read `Self.DNSName` from `tailscale status --json`, trim the trailing dot, resolve
that exact name from the controller, and prove OpenSSH key login with Yoke's
known_hosts file. Use the reported name rather than assuming LAB_NAME equals
the final name: the existing native lab reported `winnative.taile868e2.ts.net`.
Register the verified MagicDNS name as `host` with the as-read settings token,
with `desktop_route=direct` and no `desktop_host`; the OS guide's desktop setup
confines the desktop port to the tailnet. Never change a target with an active
QA lease. Follow the OS guide's verify/power-cycle and public-IP cleanup steps.

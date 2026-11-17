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

## Join native Windows through Azure SYSTEM

The registered SSH user, such as `yokeqa`, is standard and cannot install the
machine service. On the controller, save this PowerShell as `join-tailnet.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
$msi = Join-Path $env:TEMP 'tailscale-setup.msi'
Invoke-WebRequest 'https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi' -OutFile $msi
$install = Start-Process msiexec.exe -ArgumentList @('/i', $msi, '/qn', '/norestart', 'TS_UNATTENDEDMODE=always') -Wait -PassThru
if ($install.ExitCode -notin @(0, 3010)) { throw "Tailscale MSI exit $($install.ExitCode)" }
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
& $ts up --unattended --timeout=20s
$status = & $ts status --json | ConvertFrom-Json
$status.AuthURL
$status.BackendState
$status.Self.DNSName
```

Run that file through the Azure VM agent, which executes it as SYSTEM:

```sh
az vm run-command invoke -g GROUP -n VM --command-id RunPowerShellScript --scripts @join-tailnet.ps1
```

The bounded `up` can time out while sign-in awaits approval. Read `AuthURL`
from the JSON status and hand that link to the operator; do not loop installs
or claim readiness from the MSI exit alone. After approval, use another bounded
Run Command to read `tailscale status --json` and confirm it is connected.
Install Windows Tailscale on Windows only, never inside WSL. A Windows/WSL
host with an administrator desktop can use the same MSI and elevated
`tailscale up --unattended` flow locally; preserve the standard test account.

## Operator approval and registration

The operator opens each device's sign-in link, approves it in the intended
tailnet, then disables device key expiry in the Tailscale admin console.
Join the controller to that same tailnet and enable MagicDNS. Confirm the host's
service stays connected after logout/reboot before accepting unattended setup.

Read `Self.DNSName` from `tailscale status --json`, trim the trailing dot, resolve
that exact name from the controller, and prove OpenSSH key login with Yoke's
known_hosts file. Use the reported name rather than assuming LAB_NAME equals
the final name: the existing native lab reported `winnative.taile868e2.ts.net`.
Register the verified MagicDNS name as `host` with the as-read settings token;
keep forwarded `desktop_host` on loopback. Never change a target with an active
QA lease. Follow the OS guide's verify/power-cycle and public-IP cleanup steps.

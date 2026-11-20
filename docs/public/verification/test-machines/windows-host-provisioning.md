# Provisioning and saving a Windows WSL2 Test Machine

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Windows host provisioning
<!-- /yoke:breadcrumbs -->

Follow the [normal-user installation rule](index.md#install-as-the-test-user).

Follow [setup responsibilities](setup-responsibilities.md) and the project-owned
manual preparation inventory in the [provisioning index](host-provisioning.md).

Follow this ordered procedure from a bare Windows host through a proved saved
Linux home. Yoke runs inside WSL2 Ubuntu, not native Windows. The registered
SSH account is a Windows user; its default Ubuntu user is dedicated/non-root.
Infrastructure, account names, endpoints, passwords and paths are project-owned.

## 1. Infrastructure and Windows account

Declare infrastructure in the project's IaC, or record the operator's explicit
exception before provision. For a cloud host, use an image/instance supporting
Windows and WSL2 nested virtualization; declare the provider's nested-
virtualization option and validate it on the host. Do not infer support from an
instance family name. Apply the project's cost gate and query current costs.
Size the Windows system volume for Windows plus the WSL distribution's
`ext4.vhdx`, which grows with every golden and CLI install and never shrinks on
its own. When that volume fills, Linux remounts its root read-only and a golden
refresh stops with `harness_cli_host_disk_failed`: grow the volume, extend the
Windows partition, run `wsl --shutdown`, then rerun the QA plan.
Record the instance's `cloud_instance_id` (section 3): a lease then starts the
host through the project's aws-admin key and waits for SSH. The host stays
running after release. Never start it
by hand to satisfy a documentation audit without authorization.

Create a dedicated standard Windows test user and use that account for SSH
and for its [WSL and Ubuntu setup](#3-wsl2-ubuntu-and-systemd). Separate operator users/homes remain outside capture,
restore, inspection and logout. Open SSH to any address with key-only
authentication and keep RDP off public networks, as
[network access](host-provisioning.md#network-access) requires.
A lease keeps the registered MagicDNS host unchanged.

### Join Tailscale before registration

Follow [tailnet bootstrap](tailnet-bootstrap.md) for provider start, current-IP
SSH, stable lab naming and operator sign-in approval before these OS checks.

Install Tailscale on the host and join the operator's tailnet by completing its
sign-in flow. Enable startup/unattended operation and disable device key expiry
in the admin console. Controllers join the same tailnet and use MagicDNS.
This is one-time manual machine setup.

Install [Tailscale for Windows](https://tailscale.com/download/windows) on the
Windows host only, never inside WSL. Run elevated PowerShell:
`& 'C:\Program Files\Tailscale\tailscale.exe' up --unattended` and complete the
sign-in URL. Require its service to stay connected after logout/reboot.

Read `Self.DNSName` from `tailscale status --json`, trim the trailing dot and
resolve that exact MagicDNS name from the controller. Prove OpenSSH key login,
then register it as `host`; the direct desktop route uses that name too.
For cloud bootstrap, query the provider's **current** public IP and connect with
the [bootstrap SSH command](tailnet-bootstrap.md#start-the-lab-and-reach-its-current-address);
never register that IP.
Keep key-only internet SSH open from anywhere; desktops stay on the tailnet.
EC2 uses auto-assigned public IPv4 while running, with no Elastic IP.
Power starts by instance id and waits for SSH on the registered MagicDNS name.
Cloud hosts stay running after lease release. See the
[manual stop commands](host-provisioning.md#stop-a-cloud-test-machine) for
operator shutdown. Golden reset never touches Tailscale.

Before rebuilding, remove the old tailnet device first, then join the replacement
with the same hostname; verify no `-1` suffix. Verify the new SSH fingerprint,
then clear the old cloud instance-id pin using
`ssh-keygen -R INSTANCE_ID -f KNOWN_HOSTS` in Yoke's Test Machine known_hosts file
(physical hosts use the hostname pin). Re-read settings and use the as-read token
with `settings-replace` for any change, then run `yoke test-machine verify`.
If DNS/SSH fails, check Tailscale startup, device expiry, controller DNS and sshd;
never fix reachability by changing the target while its lease is active.

Existing public-IP registrations: join first, deploy the no-rebind build second,
then settings-replace `host` with MagicDNS using the as-read token. Upgrading
clients prevents old calls to the retired rebind function. Verify across a power
cycle and require the same host with no remaining QA_HOST afterward.

## 2. Windows SSH, registration and desktop secrets

Install the Windows OpenSSH Server feature and configure `sshd` to start
automatically. Authorize the project's shared test-machine public key;
administrator accounts use
`%ProgramData%\ssh\administrators_authorized_keys`, restricted to
Administrators/SYSTEM. Disable password SSH authentication and verify the
effective config. Keep private keys out of user data, settings and evidence.

Check Windows network profile and firewall together: the default OpenSSH rule
can be Private-only while the cloud interface is Public. Scope the rule to
the applicable profile and allow any source address. Open no other public
inbound port; the WSL desktop's only inbound rule is the Tailscale-only rule in
[desktop provisioning](windows-desktop-provisioning.md).

Register the Test Machine by name through `yoke test-machine settings-replace --test-machine NAME --settings-file FILE --new`; read `--help` for
updates with the as-read settings token. Declare `resource_name`, `os=wsl`,
Windows MagicDNS `host` and `user`, and an absolute **Linux** `golden_baseline_path`
outside the WSL home. Desktop fields declare `desktop_protocol=rdp`,
`desktop_route=direct` with no `desktop_host` (a host outside the tailnet uses
`ssh-forward`), the provisioned WSL xrdp port (default3390), and the dedicated
WSL `desktop_user`. Optional `cloud_instance_id` (the
EC2 instance id; leases power the host by it) and operating notes record local
infrastructure facts. Capacity registration is independent.

On every QA execution workstation, store capability-owned credentials:

```text
yoke test-machine secret set --test-machine NAME --key ssh_private_key --value-file KEY_FILE
yoke test-machine secret set --test-machine NAME --key desktop_password --value-file PASSWORD_FILE
yoke test-machine get --test-machine NAME
```

Read each command's `--help`. Desktop and SSH usernames may differ; their
credentials are independent. No password/key bytes enter argv, logs, source,
artifacts or control-plane settings. A host leased by another session is a
wait, not permission to disturb it.

Set and maintain [capability tags](host-provisioning.md#register-capability-tags) before verifying.

## 3. WSL2 Ubuntu and systemd

Follow [Microsoft's WSL installation](https://learn.microsoft.com/en-us/windows/wsl/install)
for the selected Windows release. From the standard test user's desktop, run
`wsl --install --no-distribution --web-download`. Supply Administrator
credentials at the UAC prompt for the Windows components and reboot when
required. Back in the standard account, install and launch Ubuntu 24.04,
select it as the default distribution, and prove version 2 with
`wsl --list --verbose`. The distro belongs to the Windows user who sets it up.
If WSL under a service context reports absent, verify the account identity;
use Microsoft's published offline MSI only with its published integrity proof.

Create the dedicated non-root Linux user and set `/etc/wsl.conf`:

```ini
[boot]
systemd=true
[user]
default=TESTUSER
```

Save work in all distributions, run `wsl --shutdown` from Windows, then reopen
Ubuntu. This stops every running WSL distribution, not just this fixture.
Prove the default Linux `id -u` is nonzero and PID1 is systemd. Registered host
operations enter `wsl.exe --cd ~ -e /bin/bash -lc`; home/baseline paths are Linux
paths and the operation preserves the Linux program's exit status.
Confirm from the workstation with `yoke test-machine exec --test-machine
NAME -- 'id -u; uname -a'`; read `--help`. Ad hoc exec uses its workstation SSH
agent and refuses another session's lease.

## 4. Linux tools and privileged prerequisites

Inside that Ubuntu home, an administrator installs:

```text
sudo apt-get update
sudo apt-get install -y ca-certificates curl git tmux python3 python3-venv nodejs npm
sudo install -d -m 0700 -o TESTUSER -g TESTUSER /var/lib/yoke-golden/TESTUSER
```

Complete the project's manual runtime preparation inside WSL; if it declares
Docker, install/verify Compose v2, daemon/service access and real workloads, then
reopen the session after group changes. Give the dedicated test user
passwordless sudo for automatic Chromium library setup, through a validated
0440 `/etc/sudoers.d/yoke-test-user` drop-in containing
`TESTUSER ALL=(ALL) NOPASSWD: ALL`. Administrator runs `visudo -c`; the user
proves `sudo -n true` plus the project-declared runtime workload checks.
Runtime group membership is not the privileged-library prerequisite.
Require Ubuntu24.04, Git/tmux/Python versions, non-root ownership and supported
vendor Node/runtime versions. Packages/services are outside the saved home.
Keep repositories and harnesses in the Linux filesystem. A mission that
needs a Windows application uses the registered Windows console, with its
commands still running inside the default WSL distro.

## 5. Harness sign-in and standard acceptance

Install vendor CLIs as the Linux test user, with `.local/bin` on its login PATH:

```text
curl -fsSL https://claude.ai/install.sh -o /tmp/claude-install
bash /tmp/claude-install
curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/codex-install
sh /tmp/codex-install
curl -fsSL https://cursor.com/install -o /tmp/cursor-install
bash /tmp/cursor-install
```

Confirm actual executable paths and versions. Golden capture records each CLI's version beside the golden in
`GOLDEN.harness-clis`. Before a QA plan's first reset on this host, Yoke
compares those versions with each vendor's latest release; when one is newer
it resets, installs the newer CLIs with each vendor's installer as the test user and
captures a new golden under the plan's own host lease. Do not hand-update
CLIs for QA; a failed refresh stops the plan with the step to repair.
Read current
[Claude requirements](https://code.claude.com/docs/en/setup),
[Codex installation](https://developers.openai.com/codex/cli), and
[Cursor installation](https://cursor.com/docs/cli/installation).
Installation/sign-in take place in the WSL test user's terminal, not another
Windows account or native app credential store.

Follow the [browser identity procedure](windows-browser-identities.md)
for native login. Use Claude's documented login flow; Codex
`codex login --device-auth` where [account/workspace policy allows it](https://developers.openai.com/codex/auth);
Cursor `NO_OPEN_BROWSER=1 agent login` and its printed URL
([authentication](https://cursor.com/docs/cli/reference/authentication)).
Once per fixture,
accepts Claude's dangerous-mode prompt; require
`skipDangerousModePermissionPrompt=true` before capture.

Each harness must answer a real request without tool calls. Login status or a
present credential file cannot establish it; Cursor status may exit zero while
signed out. Standard Windows/WSL capture checks cover native requests and
bypass acceptance. A custom probes file must include all standard checks and
can add Docker/service/file assertions with absolute argv and positive output
expectations. Standard names are `Claude real request`, `Codex real request`,
`Cursor real request`, and `Claude bypass accepted`; missing names refuse as
`baseline_standard_probes_missing`. Capture seals canonical standard programs
plus extras, never implicitly carrying an old sidecar forward. Read the
capture command's served `--help`. Harness output stays on the host.
macOS Keychain checks do not apply to WSL.

## 6. Windows desktop and browser coverage

Complete [WSL desktop provisioning](windows-desktop-provisioning.md) before
capture. It owns XFCE/xrdp, Chromium, unattended distro lifetime and the
Windows autologon console. Configure `wsl_desktop_session` on the test machine
to select the display for mission GUI commands and screenshots.

## 7. Save and prove the Linux home

For a first bare Linux home, keep Yoke/uv state absent before capture. With an
existing golden, reset before refreshing signed-in fixture state and re-save.
Choose a new absolute Linux destination outside the Linux home; never reuse a
Windows path or overwrite a saved baseline:

```text
yoke test-machine golden-capture --test-machine NAME --destination /var/lib/yoke-golden-DATE-UNIQUE/home
yoke test-machine verify --test-machine NAME
yoke test-machine reset --test-machine NAME --baseline fresh-host
yoke test-machine get --test-machine NAME
```

Read each command's `--help`. Capture runs standard probes before registering
the new golden. Failure leaves the current path unchanged. Its private Linux
`home.tar.gz`, `manifest.json` and sealed probes bind UID/home/archive digest.
Sockets and unsafe links are omitted; regular `.sock` files remain. Live Linux
SSH material and the browser identity store `.yoke-browser-identities` are
preserved. Windows settings/OpenSSH/WSL registration and OS
packages survive the Linux home reset and require independent assertions.

Verify is **destructive**: it reaches both baselines and ends with Yoke
installed in `shell-preconfigured`. The final reset restores only the clean
signed-in `fresh-host`. It validates the seal, stops owned services/home
writers, restores files/modes, proves product residue absent on Linux shells,
and reruns declared probes. The Linux live sign-in rule applies in WSL: the
Claude, Codex and Cursor login files never enter a golden and stay live through
every reset. It never changes Windows credentials.
Require passing receipts after a reset and actual harness requests. Verify
must prove the unlocked Windows console and a WSL command started in it
for machines that declare `wsl_desktop_session`.

## 8. Recovery and cost-bound handoff

Read every refusal's cause/reason/recovery before retrying. An occupied golden
needs a new destination; a foreign-owned entry needs operator repair. Failed
requests require sign-in or their named network/timeout remedy. A live human
desktop or mounted drive that blocks Linux clear must be logged out/unmounted
through its owner, not forcibly killed. A surviving home writer or failed clear
must be resolved before retrying the existing sealed baseline.

Linux capture/restore permits20minutes. A timeout/disconnected SSH does not
prove the remote process stopped: wait for or stop that exact process before
retry. A partially restored home is never a new baseline, and an unsealed
archive/edited manifest cannot earn proof. Never export auth material to repair
a check. When a sign-in expires, agents rerun the login, the operator types only
their password, and agents save it at once
with `yoke test-machine golden-capture`, which proves the real requests and
seals a new clean golden.

After restart, the local universe's documented startup path restarts its authority.
Record the exact saved-state proof. To shut down cloud compute after the test
window, use the [manual stop commands](host-provisioning.md#stop-a-cloud-test-machine).
A stopped host's old receipt cannot establish today's readiness.

Cloud SSH routes use `HostKeyAlias=<cloud_instance_id>` instead of an IP pin.
The first connection accepts the instance key once with `accept-new`; later
address changes keep that identity. If the instance is rebuilt, verify its new
key, then remove the old alias with `ssh-keygen -R INSTANCE_ID -f KNOWN_HOSTS`
from the Yoke-managed Test Machine known_hosts file before reconnecting.

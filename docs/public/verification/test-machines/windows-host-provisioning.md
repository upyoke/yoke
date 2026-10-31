# Provisioning and saving a Windows WSL2 Test Machine

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Windows host provisioning
<!-- /yoke:breadcrumbs -->

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
Record the instance's `cloud_instance_id` (section 3): a lease then starts the
host through the project's aws-admin key and waits for SSH, and the end of
its last lease stops it, so it runs only while QA holds it. Never start it
by hand to satisfy a documentation audit without authorization.

Create/use the dedicated Windows SSH account. WSL distributions are per Windows
user: installing under a service or another administrator account does not
prepare the test account. Separate operator users/homes remain outside capture,
restore, inspection and logout. Restrict SSH and RDP ingress to approved
execution machines or private-network routes.
Each lease start re-reads the instance public IPv4 and updates `host` before
SSH; its last lease release stops the cloud host.

## 2. Windows SSH, registration and desktop secrets

Install the Windows OpenSSH Server feature and configure `sshd` to start
automatically. Authorize the project's shared test-machine public key;
administrator accounts use
`%ProgramData%\ssh\administrators_authorized_keys`, restricted to
Administrators/SYSTEM. Disable password SSH authentication and verify the
effective config. Keep private keys out of user data, settings and evidence.

Check Windows network profile and firewall together: the default OpenSSH rule
can be Private-only while the cloud interface is Public. Scope the rule to
the applicable profile while retaining restricted source access; do not open
the network broadly as a connectivity workaround.

Register `test-machine:<name>` through `yoke test-machine settings-replace
--project P --test-machine NAME --settings-file FILE --new`; read `--help` for
updates with the as-read settings token. Declare `resource_name`, `os=windows`,
Windows `host` and `user`, and an absolute **Linux** `golden_baseline_path`
outside the WSL home. Desktop fields declare `desktop_protocol=rdp`,
`desktop_route=ssh-forward` (or an approved direct route), the provisioned
WSL xrdp port (default3390), and the dedicated WSL `desktop_user`. Optional `cloud_instance_id` (the
EC2 instance id; leases power the host by it) and operating notes record local
infrastructure facts. Capacity registration is independent.

On every QA execution workstation, store capability-owned credentials:

```text
yoke projects capability secret set --project P --cap-type test-machine --key ssh_private_key --value-file KEY_FILE
yoke projects capability secret set --project P --cap-type test-machine:NAME --key desktop_password --value-file PASSWORD_FILE
yoke test-machine get --project P --test-machine NAME
```

Read each command's `--help`. Desktop and SSH usernames may differ; their
credentials are independent. No password/key bytes enter argv, logs, source,
artifacts or control-plane settings. A host leased by another session is a
wait, not permission to disturb it.

## 3. WSL2 Ubuntu and systemd

Follow [Microsoft's WSL installation](https://learn.microsoft.com/en-us/windows/wsl/install)
for the selected Windows release. In elevated PowerShell enable
`Microsoft-Windows-Subsystem-Linux` and `VirtualMachinePlatform`, install WSL
(`wsl --install --no-distribution --web-download` for this documented path),
and reboot when required. Under the test Windows account install Ubuntu24.04,
select it as the default distribution, and prove version 2 with
`wsl --list --verbose`.
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
Confirm from the workstation with `yoke test-machine exec --project P --test-machine
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
Keep repositories in the Linux filesystem; native Windows Yoke and Windows-side
harness desktop reach-in are not covered by this fixture.

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

Registered terminal QA uses tmux transcripts. GUI commands and
`yoke test-machine screenshot --project P --test-machine NAME --json` start or
reuse the same WSL XFCE display through the existing Linux desktop helper;
the screenshot captures that display, including its actual headed browser.
Declare the dedicated WSL user as `desktop_user` and its loopback xrdp port
as `desktop_port`; the Windows SSH user remains the account owning the distro.
The capability-owned fixture password is streamed on private stdin. Another
user's ambiguous desktop refuses; no native Windows RDP login is needed.

For a requested, announced personal application sign-in handoff, run:

```text
yoke test-machine desktop-access --project P --test-machine NAME --view
```

Read `--help`. Install FreeRDP's visible SDL client on the executing workstation
(macOS: `brew install freerdp`; Linux: the distribution's `freerdp-sdl` package).
The product opens the SSH forward and supplies the fixture credential on stdin,
with the existing XFCE dimensions and color depth so xrdp reconnects that display.
It creates no password file. Close the viewer or interrupt the retained command
to close its forward. The user types only their own password or credential.
Tests use agent captures; human viewing is never a test acceptance check.
A connected viewer counts as human adoption: baseline reset/capture must wait
until it closes, even when automation originally started XFCE.

For the selected Server route, reuse Yoke's Linux XFCE/xrdp provisioner
inside WSL with a separate loopback port. The executing operation runs its
stdlib-only helper in the dedicated Linux user's home. Copy both
`provision_linux_desktop.py` and `provision_windows_wsl_desktop.py` from the
controller's `yoke_harness/host_provisioning/` package directory into that
working directory first:

```text
python3 provision_windows_wsl_desktop.py --desktop-password-stdin
python3 provision_windows_wsl_desktop.py --verify
```

The wrapper requires Ubuntu24.04, non-root passwordless sudo, WSL2/systemd and
Windows interop, with WSL3.0.1 or newer (the verified configuration support floor).
It records actual Windows edition/build and WSL version,
installs the existing Linux desktop packages, including the Chromium snap as
the default browser that [browser approval gates](linux-browser-identities.md#browser-approval-gates)
drive, and proves loopback/localhost access.
The product streams its capability-owned desktop secret on private stdin, sets
the dedicated WSL fixture password with `sudo -n chpasswd`. The next retained
GUI-session operation uses the existing uploaded `xrdp-sesrun` helper; no host
harness-package import is needed. No secret enters a file, argv or output. The
operator never types sudo, sets a machine password or logs into either desktop.
Agents prove candidate Chromium renders there before requesting only personal
application sign-in. Success leaves `headed_application_proved=false` until that
independent check. Provisioning starts no session; `--verify` refuses the secret flag.
No Windows firewall, auto-logon or public listener change is made.
The provisioner also owns persistent distro setup: it sets only
`[general] instanceIdleTimeout=-1` in the registered Windows user's `.wslconfig`,
preserving other keys and comments. This applies to that Windows user's WSL2
distros. A changed configuration reports `restart_required=true`; save work and
restart WSL before claiming it is applied. `--verify` checks the stored setting,
not its activation or desktop persistence. Prove XFCE and candidate Chromium
survive a gap longer than both default timers without a foreground keeper.
[Microsoft's settings reference](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)
distinguishes distro idle shutdown (15000ms) from VM idle shutdown (60000ms).
Systemd services alone do not keep WSL alive; no per-execution sleep is required.
[Microsoft documents localhost access to WSL services](https://learn.microsoft.com/en-us/windows/wsl/networking)
and [systemd prerequisites](https://learn.microsoft.com/en-us/windows/wsl/systemd).
WSLg is a separate route: its [documented GUI prerequisites](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)
name Windows10/11. A version string alone proves no Server GUI support.

### Live browser identities inside WSL

Follow [WSL browser identities](windows-browser-identities.md) before saving.

## 7. Save and prove the Linux home

For a first bare Linux home, keep Yoke/uv state absent before capture. With an
existing golden, reset before refreshing signed-in fixture state and re-save.
Choose a new absolute Linux destination outside the Linux home; never reuse a
Windows path or overwrite a saved baseline:

```text
yoke test-machine golden-capture --project P --test-machine NAME --destination /var/lib/yoke-golden-DATE-UNIQUE/home
yoke test-machine verify --project P --test-machine NAME
yoke test-machine reset --project P --test-machine NAME --baseline fresh-host
yoke test-machine get --project P --test-machine NAME
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
Require new passing receipts and actual harness requests,
plus independent Windows desktop proof. No such new roundtrip was run here.

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
Record the exact saved-state proof. A host with `cloud_instance_id` stops when
its last lease ends; stop any other cloud compute outside the authorized test
window. A stopped host's old receipt cannot establish today's readiness.

Cloud SSH routes use `HostKeyAlias=<cloud_instance_id>` instead of an IP pin.
The first connection accepts the instance key once with `accept-new`; later
address changes keep that identity. If the instance is rebuilt, verify its new
key, then remove the old alias with `ssh-keygen -R INSTANCE_ID -f KNOWN_HOSTS`
from the Yoke-managed Test Machine known_hosts file before reconnecting.
A cloud instance without a public IPv4 refuses as
`test_machine_power_no_public_address`: enable a public IPv4 in its subnet and
rerun. `test_machine_host_rebind_refused` preserves the server refusal; fix its
named cause, re-read the Test Machine and rerun under the host lease.

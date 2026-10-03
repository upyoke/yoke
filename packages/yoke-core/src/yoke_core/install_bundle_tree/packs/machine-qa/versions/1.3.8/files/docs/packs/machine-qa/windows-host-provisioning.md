# Provisioning and saving a Windows WSL2 Test Machine

Follow this ordered procedure from a bare Windows host through a proved saved
Linux home. Yoke runs inside WSL2 Ubuntu, not native Windows. The registered
SSH account is a Windows user; its default Ubuntu user is dedicated/non-root.
Infrastructure, account names, endpoints, passwords and paths are project-owned.

Audit: `windows-lab`, **2026-10-03 UTC**. On Server2025 build26100/WSL3.0.1,
the Pack proved XFCE/xrdp and Windows localhost access to3390. After lifetime
configuration and a controlled restart, XFCE and headed Chromium retained
identical boot/display/process/window identities over125seconds with no
target call or foreground keeper; the browser step still worked. Operator
viewing, personal sign-in and profile capture/restore remain pending. The VM
was stopped and rechecked. Persistence proof does not establish own approval.

## 1. Infrastructure and Windows account

Declare infrastructure in the project's IaC, or record the operator's explicit
exception before provision. For a cloud host, use an image/instance supporting
Windows and WSL2 nested virtualization; declare the provider's nested-
virtualization option and validate it on the host. Do not infer support from an
instance family name. Apply the project's cost gate, query current costs, and
stop the host outside the approved test window. Never start it to satisfy a
documentation audit without authorization.

Create/use the dedicated Windows SSH account. WSL distributions are per Windows
user: installing under a service or another administrator account does not
prepare the test account. Separate operator users/homes remain outside capture,
restore, inspection and logout. Restrict SSH and RDP ingress to approved
execution machines or private-network routes.
An automatically assigned public IPv4 can change on stop/start; update the
registered endpoint after restart. An operator-approved Elastic IP is stable
but continues charging while stopped; it belongs in infrastructure declarations.

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
--project P --machine NAME --settings-file FILE --new`; read `--help` for
updates with the as-read settings token. Declare `resource_name`, `os=windows`,
Windows `host` and `user`, and an absolute **Linux** `golden_baseline_path`
outside the WSL home. Desktop fields declare `desktop_protocol=rdp`,
`desktop_route=ssh-forward` (or an approved direct route), the provisioned
WSL xrdp port (default3390), and the dedicated WSL `desktop_user`. Optional `cloud_instance_id` and operating
notes record local infrastructure facts. Capacity registration is independent.

On every QA execution workstation, store capability-owned credentials:

```text
yoke projects capability secret set --project P --cap-type test-machine --key ssh_private_key --value-file KEY_FILE
yoke projects capability secret set --project P --cap-type test-machine:NAME --key desktop_password --value-file PASSWORD_FILE
yoke test-machine get --project P --machine NAME
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
select it as the default distribution, and prove version2 with
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
Confirm from the workstation with `yoke test-machine exec --project P --machine
NAME -- 'id -u; uname -a'`; read `--help`. Ad hoc exec uses its workstation SSH
agent and refuses another session's lease.

## 4. Linux tools and privileged prerequisites

Inside that Ubuntu home, an administrator installs:

```text
sudo apt-get update
sudo apt-get install -y ca-certificates curl git tmux python3 python3-venv nodejs npm docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker TESTUSER
sudo install -d -m 0700 -o TESTUSER -g TESTUSER /var/lib/yoke-golden/TESTUSER
```

Reopen the user's session after group changes. Give the dedicated test user
passwordless sudo for automatic Chromium library setup, through a validated
0440 `/etc/sudoers.d/yoke-test-user` drop-in containing
`TESTUSER ALL=(ALL) NOPASSWD: ALL`. Administrator runs `visudo -c`; the user
proves `sudo -n true` and `docker info`. Docker-group membership alone is not
the privileged-library prerequisite.
Require Ubuntu24.04, Git/tmux/Python versions, non-root ownership and supported
vendor Node/runtime versions. Packages/services are outside the saved home.
Keep repositories in the Linux filesystem; native Windows Yoke and Windows-side
harness desktop reach-in are not covered by this fixture.

## 5. Harness sign-in and standard acceptance

Install vendor CLIs as the Linux test user, with `.local/bin` on its login PATH:

```text
curl -fsSL https://claude.ai/install.sh -o /tmp/claude-install
bash /tmp/claude-install
npm install --global --prefix "$HOME/.local" @openai/codex
curl -fsSL https://cursor.com/install -o /tmp/cursor-install
bash /tmp/cursor-install
```

Confirm actual executable paths and versions. Read current
[Claude requirements](https://code.claude.com/docs/en/setup),
[Codex installation](https://developers.openai.com/codex/cli), and
[Cursor installation](https://cursor.com/docs/cli/installation).
Installation/sign-in take place in the WSL test user's terminal, not another
Windows account or native app credential store.

Operator sign-in uses Claude's documented login flow; Codex
`codex login --device-auth` where [account/workspace policy allows it](https://developers.openai.com/codex/auth);
Cursor `NO_OPEN_BROWSER=1 agent login` and its printed URL
([authentication](https://cursor.com/docs/cli/reference/authentication)).
The operator opens URLs/enters codes personally. Once per fixture, the operator
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
`yoke test-machine screenshot --project P --machine NAME --json` start or
reuse the same WSL XFCE display through the existing Linux desktop helper;
the screenshot captures that display, including its actual headed browser.
Declare the dedicated WSL user as `desktop_user` and its loopback xrdp port
as `desktop_port`; the Windows SSH user remains the account owning the distro.
The capability-owned fixture password is streamed on private stdin. Another
user's ambiguous desktop refuses; no native Windows RDP login is needed.

For operator viewing, run:

```text
yoke test-machine desktop-access --project P --machine NAME --view
```

Read `--help`. Install FreeRDP's visible SDL client on the executing workstation
(macOS: `brew install freerdp`; Linux: the distribution's `freerdp-sdl` package).
The product opens the SSH forward and supplies the fixture credential on stdin,
with the existing XFCE dimensions and color depth so xrdp reconnects that display.
It creates no password file. Close the viewer or interrupt the retained command
to close its forward. Operator work begins at a personal application's sign-in,
not a desktop login. Native Windows display evidence does not prove this route.
A connected viewer counts as human adoption: baseline reset/capture must wait
until it closes, even when automation originally started XFCE.

For the selected Server route, reuse this Pack's Linux XFCE/xrdp provisioner
inside WSL with a separate loopback port. The executing operation runs its
stdlib-only helper in the dedicated Linux user's home:

```text
python3 ops/machine-qa/provision_windows_wsl_desktop.py --desktop-password-stdin
python3 ops/machine-qa/provision_windows_wsl_desktop.py --verify
```

The wrapper requires Ubuntu24.04, non-root passwordless sudo, WSL2/systemd and
Windows interop, with WSL3.0.1 or newer (the verified configuration support floor).
It records actual Windows edition/build and WSL version,
installs the existing Linux desktop packages and proves loopback/localhost access.
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

### Separate signed-in browser profile inside WSL

A clean-home golden excludes the project's Yoke browser profile. Save that
profile as a separate component; it never makes a partial home a valid golden.

1. Agents use the registered test user and leased product operations to install
   the candidate and prepare its Chromium runtime and real headed desktop.
   This gives the user space for whatever sign-ins their project needs.
2. Agents open `yoke browser authorize --project P --url APPLICATION_URL`
   as the test user in the real headed desktop; read `--help`. The user chooses
   whatever sign-ins their project needs and supplies personal credentials.
   Agents complete routine setup and password-free application steps from an
   existing saved identity-provider session. Password, MFA, passkey and personal
   permission prompts require the user; agents never enter those credentials or
   change security settings.
3. The operator closes every authorization Chromium window and waits for the
   command to finish. Authorization stops the daemon before opening its plain
   Chromium and shuts that process down after its windows close. Do not start
   another browser case between this closure and capture. From the execution
   workstation, seal a new separate component:

   ```text
   yoke test-machine golden-capture --project P --machine NAME --component browser-profile --json
   ```

   Read `--help` for a new sibling destination. No probes file is needed.
   The capture refuses active writers, unavailable inventory, unsafe/foreign
   entries and occupied destinations. Private contents stay on the host;
   receipt success records `browser_profile_baseline_path` while preserving
   the clean `golden_baseline_path`. Keep the live profile if capture refuses;
   fix the named condition before resetting. Missing ancestors are created
   owner-only; existing permissions are never silently changed.
   A test-user-owned readable golden parent is permitted; other-user write
   access is refused with its path. The sealed snapshot stays owner-only.
4. Disconnect the human desktop before any destructive baseline reset. Reset
   restores the clean home and removes its live Yoke profile. Install the
   candidate, then explicitly restore before daemon startup:

   ```text
   yoke qa browser setup --project P --profile-baseline RECORDED_ABSOLUTE_PATH --json
   ```

   Exploratory walkers run this through their retained mission host-command.
   Scripted cases place this fixture after candidate installation:

   ```json
   {"id":"machine.browser-profile-restore","parameters":{"project":"CANONICAL_SLUG","baseline_path":"RECORDED_ABSOLUTE_PATH"}}
   ```

   Both routes check identity/digest and refuse an existing profile or active
   writers. Default setup and dry-run never restore a profile.
5. Start the installed candidate browser from the restored profile. Verify
   that its runtime opens on the real display and retains the separate profile.
   Archive integrity and browser liveness are separate evidence; saved sessions
   can expire even when the archive remains intact.
6. Agents perform application steps that do not need the user. Credential entry
   is a precise `HUMAN_GATE` naming the machine, current screen, needed personal
   action and resume state. Preserve the profile at a handoff. Runtime and
   inventory failures retain their named diagnostics.

The candidate Chromium and profile both live under the non-root WSL test user.
The operator needs an actually working headed WSL display; a native Windows
Edge/Chrome sign-in cannot populate this Linux candidate profile. Prove the
Linux application visibly renders before requesting a personal sign-in. If
the provisioned WSL display is unavailable, return its named failure; do not
change system settings or invent native-profile exports. Linux writer inventory
and private archive work run inside WSL.
This route on windows-lab is pending real capture/restore proof.

## 7. Save and prove the Linux home

For a first bare Linux home, keep Yoke/uv state absent before capture. With an
existing golden, reset before refreshing signed-in fixture state and re-save.
Choose a new absolute Linux destination outside the Linux home; never reuse a
Windows path or overwrite a saved baseline:

```text
yoke test-machine golden-capture --project P --machine NAME --destination /var/lib/yoke-golden/TESTUSER/home-DATE
yoke test-machine verify --project P --machine NAME
yoke test-machine reset --project P --machine NAME --baseline fresh-host
yoke test-machine get --project P --machine NAME
```

Read each command's `--help`. Capture runs standard probes before registering
the new golden. Failure leaves the current path unchanged. Its private Linux
`home.tar.gz`, `manifest.json` and sealed probes bind UID/home/archive digest.
Sockets and unsafe links are omitted; regular `.sock` files remain. Live Linux
SSH material is preserved. Windows settings/OpenSSH/WSL registration and OS
packages survive the Linux home reset and require independent assertions.

Verify is **destructive**: it reaches both baselines and ends with Yoke
installed in `shell-preconfigured`. The final reset restores only the clean
signed-in `fresh-host`. It validates the seal, stops owned services/home
writers, restores files/modes, proves product residue absent on Linux shells,
and reruns declared probes. Linux Claude credential refresh preservation
applies in WSL; it does not preserve Codex/Cursor live refresh state or change
Windows credentials. Require new passing receipts and actual harness requests,
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
a check. When a restored sign-in expires, the operator signs in, proves real
requests, and saves a new clean golden.

After restart, the local universe's documented startup path restarts its authority.
Record the exact saved-state proof and stop cloud compute outside the authorized
test window. A stopped host's old receipt cannot establish today's readiness.

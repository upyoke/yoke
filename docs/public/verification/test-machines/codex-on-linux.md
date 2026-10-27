# Codex on a dedicated Linux Test Machine

Return to [Linux provisioning](linux-host-provisioning.md) after these checks.
Record each fixture adjustment, its operator approval and observed result in
the project's operating record. Approval for one machine covers that machine.

## Unattended posture

Use Yoke's setup permission pass after the operator approves the fixture's
unattended posture. Codex's required persisted values are
`approval_policy = "never"` and `sandbox_mode = "danger-full-access"`.

```text
yoke setup --help
yoke setup --agent
```

Follow the printed answers, reuse the approved connection, preserve the
project's GitHub choice and inspect Review before applying. The permission
pass always applies unattended posture to every detected harness.
If Review changes a harness outside the approved scope, stop and request
explicit approval for those additional changes.
Do not substitute a direct config edit or an internal Python helper.

Setup cannot continue under a permission hold: approve unattended posture
for every installed harness before applying. Preserve a saved agent setup's
choices and follow its printed recovery if those choices need to change.

After applying an approved plan, re-check the installed health result:

```text
yoke doctor run --install
```

Record the active harness's authentication, posture and hook/session results
separately. A registered machine or relay heartbeat does not prove a live hook
or one orientation. Keep unresolved readiness checks unresolved; another
harness's settings do not establish Codex readiness. Verify the actual CLI
build against installed discovery requirements, separately from its daemon.

An existing conversation can retain its earlier sandbox after setup changes
the persisted settings. Resume that same conversation with the already
approved posture, then verify its next actual turn context:

```text
codex resume --ask-for-approval never --sandbox danger-full-access SESSION_ID
```

Preserve the conversation, profile and sign-in. These flags require the same
fixture approval as the setup pass; they do not grant permission elsewhere.

## Embedded helper and AppArmor

If a harmless native sandbox command fails with a `bwrap` user-namespace or
loopback permission denial, inspect the kernel audit before changing policy.
Codex can run an embedded helper under
`~/.codex/packages/app-server-daemon/releases/BUILD/codex-resources/bwrap`;
an npm frontend can use its package's embedded helper instead. The frontend
version or a system `bwrap` path does not identify the executed helper.

For an operator-approved fixture repair, preserve the existing AppArmor file
and add an attachment only for the exact executable named by the audit.
Retain older exact attachments needed by other installed builds. The fixture
attachment uses `flags=(unconfined)` with `userns,`; keep
`kernel.apparmor_restrict_unprivileged_userns=1`. Reload the named policy with
`sudo apparmor_parser -r /etc/apparmor.d/codex-bwrap`, then repeat the same
harmless command in the same native session. Do not use a wildcard attachment
or a global user-namespace relaxation as a substitute.

Record the audited path, before/after policy and real rerun result without
credentials. Preserve signed-in profiles; the machine's declared starting
state still governs reset and golden capture.

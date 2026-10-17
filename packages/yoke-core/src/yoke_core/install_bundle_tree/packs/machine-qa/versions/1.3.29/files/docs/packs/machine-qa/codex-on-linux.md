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
pass covers every detected harness and preserves explicit existing settings.
If Review changes a harness outside the approved scope, stop and request a
registered scoped route or explicit approval for those additional changes.
Do not substitute a direct config edit or an internal Python helper.

`--skip-harness-permissions` preserves permissions when setup must continue
under a hold. A saved agent setup rejects changed flags: preserve its choices
and follow its printed staged-setup discard recovery before starting with the
new flag. This removes setup answers, not credentials or installed software.

After applying an approved plan, re-check the installed health result:

```text
yoke doctor run --install
```

Record the active harness's authentication, posture and hook/session results
separately. A registered machine or relay heartbeat does not prove a live hook
or one orientation. Keep unresolved readiness checks unresolved; another
harness's settings do not establish Codex readiness. Verify the actual CLI
build against installed discovery requirements, separately from its daemon.

## Embedded helper and AppArmor

If a harmless native sandbox command fails with a `bwrap` user-namespace or
loopback permission denial, inspect the kernel audit before changing policy.
Codex can run an embedded helper under
`~/.codex/packages/app-server-daemon/releases/BUILD/codex-resources/bwrap`;
the frontend version or a system `bwrap` path does not identify that helper.

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

# Golden baseline semantics

Preparing, signing in, saving, restoring and repairing a Test Machine has one
complete ordered procedure per OS in the Machine QA Pack:

- [macOS](../../packs/machine-qa/versions/1.3.12/files/docs/packs/machine-qa/macos-host-provisioning.md)
- [Linux](../../packs/machine-qa/versions/1.3.12/files/docs/packs/machine-qa/linux-host-provisioning.md)
- [Windows/WSL2](../../packs/machine-qa/versions/1.3.12/files/docs/packs/machine-qa/windows-host-provisioning.md)

The [provisioning index](../../packs/machine-qa/versions/1.3.12/files/docs/packs/machine-qa/host-provisioning.md) installs
as `docs/packs/machine-qa/host-provisioning.md`. This page explains the model
behind its evidence, without providing a second preparation procedure.

`fresh-host` is user-equivalent: vendor harnesses and their signed-in fixture
state remain available while Yoke state and launchers are absent.
`shell-preconfigured` adds the current Yoke shell launcher. Baseline identity
therefore matters independently of the operation's success flag.

The sealed home lives outside the restored home. Its manifest binds identity,
size/digest and probe document; modes and ACLs remain part of captured state.
macOS capture excludes the exact root:wheel regular audiovisual preference
`Library/Group Containers/group.com.apple.secure-control-center-preferences/Library/Preferences/group.com.apple.secure-control-center-preferences.av.plist`.
The shared preservation contract validates its owner/type and rejects symlink
ancestors, records the exclusion in the sealed manifest, and keeps the live
entry during reset alongside SSH access and user TCC. Every other foreign
entry still refuses. Older manifests remain readable; a present preservation
declaration must match the contract and the excluded entry must not be captured.
The archive is private fixture material, not a QA artifact. Whole-home content,
CLI liveness, persistent OS grants and the actual visible desktop are separate
proofs: a passing one cannot establish the others.

macOS capture omits sockets and FIFOs while retaining resource forks, extended
attributes, ACLs and file flags. Its tar stream carries extended attributes in
AppleDouble metadata rather than duplicate PAX xattr headers: sandbox container
attributes can exceed the tar reader's 1 MiB special-header limit. Any copy
error still fails capture and reports its path and message in the receipt;
partial destinations cannot be registered as a baseline.

The probes seal reports upload and chmod failures separately in the existing
`golden_probes_seal_failed` refusal. It retains the sidecar path, sub-step,
exit code and bounded remote stderr; transport exceptions name their type
when no exit status exists. Recovery preserves the failed capture and calls
for repairing the named access or SSH failure before using a new destination.
macOS chmod receives its option delimiter before the mode, so it cannot mistake
the delimiter for another file and report failure after sealing the sidecar.

Restore cannot govern objects outside the home merely by copying files.
Product-owned Compose resources, running home writers, service-manager jobs
and declared temporary residue have independent ownership/absence checks.
Compose labels protect unrelated workloads; PID start times protect reused
process ids; service inventory checks protect against deleted definitions whose
jobs remain loaded. A failed prerequisite preserves its diagnostic in the
operation receipt, and a partial restore cannot establish a new baseline.

Linux golden capture proves its own reset roundtrip and sealed probes, starts
the fixture desktop through xrdp, validates a non-blank screenshot, and ends the
session before registration. Its receipt names the failing step when any check
fails. Desktop discovery counts active logged-in fixture users, excluding
greeters, closing sessions and other users. Reset ends the fixture desktop.

Linux user-service mutations share the relay's 180-second operation budget;
inventory probes retain a 30-second limit. Timeout receipts name the command
and unsettled job. Archive failures preserve bounded, redacted native exit,
stdout and stderr through mission preparation, including malformed receipts.

The SSH access needed to finish restore remains live. Linux/WSL Claude's
post-request credential refresh is preserved through the owned restore path;
other harness credentials and macOS Keychain use their own baseline/context
contracts. Windows state and WSL registration remain outside the Linux home.
System packages remain outside home-only restoration and may additionally be
owned by a mission fixture's package journal.

Structure is not liveness: a captured credential may expire. Canonical
standard per-OS probes are sealed with every new capture, alongside extra
checks. A named harness check requires a tiny native request; status-only
output and credential-file presence are insufficient. Output stays on the
host, while readiness records retain classified cause, reason and recovery.
An undelivered bridge probe is distinct from a program that ran and refused.
Older sealed sidecars remain historical state, not implicit inputs to a new
capture's required check set.

The separate browser-profile seal belongs to a different component from
the clean home. It binds the private profile to its project/user/home and is
outside ordinary home restoration. Its archive receipt establishes identity
and integrity; signed-in application UI remains an independent proof.

[Operation contracts](test-machine-operations.md) cover leases and receipts;
[testing and verification](../testing-verification.md) covers QA verdicts.

## Yoke application sign-ins

Yoke's hosted machine-connection tests use an account able to approve a test
machine in the application paired with their plan's bound environment.
The installed `installer-campaign` plan is bound to Production and uses
`https://app.upyoke.com`. Its source template is projected onto that one plan
target; source labels are not separate environment branches in a test.
No installed machine case requires a Stage application sign-in. Installing
wheels and reaching a browser wait screen alone do not need an application
sign-in. These are Yoke test facts, not Machine QA Pack prerequisites.

Yoke's agent-driven walker case restores the separate saved profile after
candidate installation and uses it for its own fresh machine approval. The case
instructions own pages, paths, labels, controls, refusal text and completion
checks. Its existing retained host-command keeps the candidate terminal alive;
`yoke qa browser setup` and `yoke qa browser step` drive candidate Chromium one
observed step at a time. Read those commands' `--help` before execution. Do not
add an approval command or extend the scripted terminal recipe contract.
Follow the Machine QA Pack's [setup responsibilities](../../packs/machine-qa/versions/1.3.12/files/docs/packs/machine-qa/setup-responsibilities.md).
Agents complete every software-capable setup step and system permission prompt.
Only browser sign-in and OS permissions that software cannot grant need the
operator. Product code alone enters passwords from stored secrets; nobody types
them by hand. Verify a fresh authorization link belongs to this execution and
the visible signed-in identity is the intended test account before clicking.
Actual candidate application UI and terminal completion are separate proofs
from the snapshot seal. Scripted terminal cases keep their current route.
The proven Mac Safari route remains in place until the walker has completed a
real test-mac approval.

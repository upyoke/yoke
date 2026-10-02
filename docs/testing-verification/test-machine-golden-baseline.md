# Golden baseline semantics

Preparing, signing in, saving, restoring and repairing a Test Machine has one
complete ordered procedure per OS in the Machine QA Pack:

- [macOS](../../packs/machine-qa/versions/1.3.8/files/docs/packs/machine-qa/macos-host-provisioning.md)
- [Linux](../../packs/machine-qa/versions/1.3.8/files/docs/packs/machine-qa/linux-host-provisioning.md)
- [Windows/WSL2](../../packs/machine-qa/versions/1.3.8/files/docs/packs/machine-qa/windows-host-provisioning.md)

The [provisioning index](../../packs/machine-qa/versions/1.3.8/files/docs/packs/machine-qa/host-provisioning.md) installs
as `docs/packs/machine-qa/host-provisioning.md`. This page explains the model
behind its evidence, without providing a second preparation procedure.

`fresh-host` is user-equivalent: vendor harnesses and their signed-in fixture
state remain available while Yoke state and launchers are absent.
`shell-preconfigured` adds the current Yoke shell launcher. Baseline identity
therefore matters independently of the operation's success flag.

The sealed home lives outside the restored home. Its manifest binds identity,
size/digest and probe document; modes and ACLs remain part of captured state.
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

Yoke's fresh-host and installer cases restore the separate saved profile after
candidate installation and use it for their own fresh machine approval. Their
existing case step settings own pages, paths, labels, controls and refusal text.
Agents complete setup and password-free application steps from a saved identity
provider session; the user handles credential entry and personal permission
prompts. Actual candidate application UI and terminal completion are separate
proofs from the snapshot seal. The proven Mac Safari route remains in place until
the candidate route has completed a real test-mac approval.

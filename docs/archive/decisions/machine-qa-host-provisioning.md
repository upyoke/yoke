# Why Machine QA owns restorable user state

The authoritative provisioning, authentication, permission, desktop, save,
and restore procedures live in the [Machine QA Pack](../../../packs/machine-qa).
This decision record preserves architectural reasoning only.

## A whole home is the unit of restore

A cleanup roster cannot predict every future product path. The dedicated test
home captures the user's settings, applications, and signed-in harness state;
a sealed baseline outside that home lets reset prove the returned state.
A clean home contains no Yoke installation. Installation remains behavior
that each mission must exercise, while the harness vendor's own state is part
of the fixture. Separately sealed browser authorization has its own boundary.

The baseline binds the test account, home, archive identity, and probes.
Structure alone cannot prove usable authentication: credentials expire and
refresh tokens change. Native request probes establish liveness separately
from restored content. An incomplete copy or clear fails the operation.

## Control channels have an independent lifetime

SSH access must survive the home clear because it carries the restore itself.
Privacy grants also remain independent: the OS attributes grants to the
controlling process, and restoring a home cannot reestablish revoked consent.
A passing restore therefore does not imply working screen recording,
Accessibility, or Automation. The operation that needs a grant supplies its
proof; no private permission database becomes an inspection recipe.

The graphical login and an SSH login are different security contexts. A
keychain-backed command in the wrong context can report expired credentials
while its graphical session remains usable. The GUI Terminal bridge preserves
that distinction. Automatic login supplies a graphical session; it does not
give SSH access to the login keychain.

Capture and restore keep the source immutable while handling ACLs and modes
on live destinations. User ownership makes the dedicated account capable of
clearing and restoring its own fixture. Sockets and FIFOs are live process
state, not portable baseline content. Service registries and system packages
live beyond the home and require separate operation-owned handling.

## Names and ownership remain project-owned

A stable private-network name survives a host rebuild better than a transient
address. The capability record owns the current endpoint, user, baseline, and
desktop route; immutable Pack source contains reusable procedure only.
The test-machine lease is independent of relay capacity. A host that offers
both roles cannot safely run ordinary work in the home a test reset owns.

The per-OS guides keep preparation and acceptance together. Other pages link
there so the rationale, command contract, and single ordered procedure remain
separate without competing setup instructions.

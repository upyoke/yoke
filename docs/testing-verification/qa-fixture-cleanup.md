# QA fixture cleanup

Yoke's own QA cases install and connect Yoke on a Test Machine, so a walk can
leave a registered Machine, Yoke projects and GitHub repositories behind. The
QA platform tracks none of them and walk-end removes none of them: walk-end
only removes the mission's staging and restores the Test Machine. The walker
removes everything below itself, before walk-end, and reports every fixture it
created and anything it could not remove with the refusal and its recovery.

Two kinds of cleanup differ in what they need:

- **Host cleanup** changes the Test Machine, such as uninstalling a checkout.
  It needs the mission's lease and runs through `yoke qa mission host-command`.
- **Server cleanup** retires Machines and projects and deletes repositories.
  It runs on the server and needs no lease.

An abort, whether by the walk's owner or by steering, keeps the lease and
mission access until walk-end: each access reply carries a
`mission_walk_stopped` notice, the walker finishes both kinds of cleanup, then
runs walk-end, which settles the abort. If mission access is gone anyway, the
`agent_mission_access_failed` refusal names the server cleanup still owed; the
walker runs it and reports what the lost lease left on the host. The walker
never hands either kind to steering.

Every server command here runs against the server the test's `yoke connect`
reached: the hosted control plane, or a self-hosted server such as the
[temporary self-hosted server fixture](self-host-fixture.md). Pass that
server's connection with `--env ENV`; a Machine registered with a self-hosted
server does not exist on prod. Run Test Machine commands through
`yoke qa mission host-command`, never SSH around the lease.

## Find the Machine

A connected install registers a new Machine. List the Machines on the server
the test connected to and pick the one the test's connect registered (its name
and `registered_at` fall inside the walk):

```text
yoke --env ENV machine list
```

## Launch onto it

A session launch's `--machine` takes that Machine id, through the same server.
The Test Machine's name is never a launch target:

```text
yoke --env ENV session-control launch create --project P --item PREFIX-N \
  --machine MACHINE_ID --idempotency-key K
```

## Retire the Machine

Retire it once the test no longer needs it. Retirement revokes its credential
and keeps its history:

```text
yoke --env ENV machine retire MACHINE_ID --confirm
```

A retirement the walking actor may not do refuses as `machine_retire_forbidden`;
report the Machine id so its owner retires it.

## Uninstall and retire the test's projects

For each project the test created, uninstall its checkout on the Test Machine
(host cleanup), then retire the project on the server (server cleanup, even
after the lease is gone). Retirement refuses open items,
created or executing runs and held claims, so cancel the project's items and
release its claims first:

```text
yoke qa mission host-command --item PREFIX-N --execution-id ID \
  --requirement-id N -- yoke project uninstall --json CHECKOUT
yoke --env ENV projects retire --project P --reason "QA fixture cleanup"
```

Remove a checkout's linked worktrees before uninstalling it. Never retire a
project the test did not create.

## Delete the test's repositories

Delete every repository the test created with `gh repo delete OWNER/NAME --yes`,
including one the product created during the test, such as onboarding creating
`OWNER/yoke-qa-*-source`.

Never delete an upstream or pre-existing repository. List every exact
`OWNER/NAME` still present in the walker report and the final verdict.

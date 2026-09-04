# Machine registry

A Yoke machine is a host that runs a relay and harness surfaces. Many people
and many machines share one universe, so each machine is a capacity pool with
an owner, a name, and settings that say which same-universe actors may spend
that capacity.

## Why a machine needs a row

Before the registry, a machine id was only asserted. `~/.yoke/config.json`
carried a random UUID, nothing recorded it, and validation checked its format
and nothing else — so a machine had no owner, no name a person would
recognise, and no way to say who was allowed to spend its capacity. A launch
could land on any connected box, and the fleet report could only print the
UUID.

The registry closes this by giving every machine a row: an owner, a human
name, and an access document. Identity is the registered id and name; a host
that has not registered is refused at launch by name.

## The machines row

One row per machine in the control plane:

| Column | Meaning |
|---|---|
| `machine_id` | The canonical UUID from `~/.yoke/config.json`. |
| `name` | The human name, defaulting to the operator-set host name. |
| `owner_actor_id` | The actor who registered it. |
| `access` | The access document (below). |
| `registered_at` / `last_seen_at` | Registration, and the last poll seen. |

## Registering

`yoke status` registers this machine whenever it runs, so an operator does not
have to know it is a step. `yoke onboard` deliberately does not: onboarding has
to finish against a control plane that can only be inventoried, where a
function call answers 5xx and burns the whole connection retry ladder, while
status already knows whether the plane answered. Run it by hand with:

```bash
yoke machine register [--name NAME]
```

Registration is idempotent, which is what lets `yoke status` run it every time.
A machine already registered to another actor is refused as
`machine_owner_mismatch`; the recovery is to ask its owner or an administrator
to re-register it, or to clear the copied `machine_id` from
`~/.yoke/config.json` and register that host as its own machine.

`HC-machine-registry` checks the same fact locally, so an unregistered machine
is something doctor tells you before a refused launch does.

## The access document

`access` says who may use the machine's capacity and what it offers:

```json
{
  "use": {
    "mode": "owner_only",
    "actor_ids": [],
    "project_id": null,
    "role": ""
  },
  "offers": {
    "executor_surfaces": [],
    "models": [],
    "qa_host": false,
    "deploys": false
  }
}
```

`use.mode` is one of `owner_only` (the default), `actors` (the listed
`actor_ids`), `project_role` (holders of `role` on `project_id`), or
`universe` (every member). The owner and an administrator always may — an
operator locked out of a machine they own would have no recovery short of the
database. An empty `offers` list narrows nothing; a populated one is
exhaustive.

Read and change it with:

```bash
yoke machine settings get [MACHINE-ID] [--path use.mode]
yoke machine settings set [MACHINE-ID] --path use.mode --value universe
```

Only the machine's owner or an administrator may set it.

## Where access is enforced

At the one place launch capacity is consumed: `session_control.launch.preview`
and `session_control.launch.create` resolve their relays through one
eligibility snapshot, and a machine the calling actor may not use is dropped
from it with the `machine_access_denied` rejection code. The refusal message
names the setting that decided it (`access.use.mode`), so the operator knows
which knob to turn. An unregistered machine is never launchable: capacity
whose owner and settings are unknown cannot be checked.

## Reading the fleet

`yoke machine list` shows every registered machine with its owner, access
mode, and last poll seen. The fleet report's launch-balance rows, launchable
machine/surface pairs, and plan-limit rows all name machines by their
registered name. A machine with no registry row falls back to whatever that
row can offer: the plan-limit rows still have the host name its relay
reported, while the balance and pair rows have only the id.

## Related surfaces

`harness_machine_state` records which harnesses are installed and approved per
project on a machine; the machines row records the machine's identity, owner,
liveness, and access. A per-machine harness-connection fact — "which harnesses
have connected from THIS machine" — belongs on `harness_machine_state` keyed
by the registered `machine_id`, not as a third machine surface.

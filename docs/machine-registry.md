# Machine registry

A Yoke machine is a host that runs a relay and harness surfaces. Many people
and many machines share one universe, so each machine is a capacity pool with
an owner, a proved identity, and settings that say which same-universe actors
may spend that capacity.

## Why identity has to be proved

Before the registry, a machine id was only asserted. `~/.yoke/config.json`
carried a random UUID, nothing recorded it, and validation checked its format
and nothing else. The consequences were all silent:

- a copied config made two hosts one relay — under the same actor either box
  took the other's wakes and launches; under a different actor the second
  relay was refused with `relay_actor_mismatch` and no explanation of why;
- a reset id orphaned every session recorded under the old one until the
  stale-session sweep caught up;
- doctor noticed a *missing* machine id and never a changed one.

The registry closes this by asking the host to prove the id it claims.

## The machines row

One row per machine in the control plane:

| Column | Meaning |
|---|---|
| `machine_id` | The canonical UUID from `~/.yoke/config.json`. |
| `name` | The human name, defaulting to the operator-set host name. |
| `owner_actor_id` | The actor who registered it. |
| `proof_public_key` | Base64 Ed25519 public half of the machine's key. |
| `access` | The access document (below). |
| `registered_at` / `last_seen_at` | Registration, and the last proved poll. |

The private half lives in `~/.yoke/machine-key.json` (owner-only, `0600`) and
never leaves the host. It is a separate file from the machine config on
purpose: the ordinary reasons a config gets copied do not carry the secret
along.

## Registering

Registration happens at connect time on both doors — the `yoke onboard` apply
and `yoke status` — so an operator does not have to know it is a step. Run it
by hand with:

```bash
yoke machine register [--name NAME]
```

It mints the key on first use and registers its public half. Re-registration
with the same key is idempotent (which is what lets `yoke status` run it every
time). A **different** key on a known id is refused as
`machine_proof_key_conflict`: a host that copied the machine id but not the
private key would otherwise mint its own key, re-register, and quietly take
the machine over. The two recoveries the refusal names are:

```bash
yoke machine register --rotate-key   # on the machine that owns the id
```

or, on a host that copied the id, clear `machine_id` from
`~/.yoke/config.json` and register that host as its own machine.

## The relay gate

Every relay poll signs `yoke-machine-proof:v1:<machine_id>:<issued_at>` with
the machine's private key and carries the signature. The control plane refuses
the poll by name, with the recovery, when:

| Refusal | Meaning |
|---|---|
| `machine_proof_missing` | The poll carried no proof — an install predating registration. |
| `machine_unregistered` | The id is not in this control plane. |
| `machine_owner_mismatch` | The id belongs to another actor. |
| `machine_proof_invalid` | The signature does not match the registered key. |
| `machine_proof_expired` | The proof is outside the 300-second freshness window (usually a wrong clock). |

`HC-machine-registry` checks the same two facts locally: that this machine is
registered, and that its registered key still matches the local one.

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

## Rollout

The proof gate and the client that signs ship together. A machine still
running an older wheel polls without a proof and is refused by name; upgrading
that machine's install and running `yoke machine register` (or `yoke status`)
restores it. Nothing else about the machine changes.

## Reading the fleet

`yoke machine list` shows every registered machine with its owner, access
mode, and last proved poll. The fleet report's launch-balance rows, launchable
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

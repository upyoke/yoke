# Harness manifest: parallel sub-agents

The `parallel_subagents` object of
[`manifest.json`](manifest-schema.md) is rendered from
`yoke_contracts.harness_subagent_capability.HARNESS_SUBAGENT_CAPABILITIES`.
Conduct reads it before an epic fan-out: `supported` dispatches one Engineer
per ready lane at once and acts on each result as it returns; any other value
dispatches one sub-agent at a time and records that serial deferral in the
epic's Progress Log.

| Key | Type | Description |
|-----|------|-------------|
| `source` | string | Canonical Python contract that owns the fact. |
| `parallel_subagents` | string | `supported` \| `none` \| `unverified`. |
| `mechanism` | string | Named primitive that runs the sub-agents concurrently. Empty when the class is not `supported`. |
| `verified_on_surface` | string | Session surface the observation came from. Empty when unverified. |
| `evidence` | string | What was observed, and when. |

`unverified` is the default for an unknown harness id; add a measured entry to
the contract before any surface relies on concurrency there.

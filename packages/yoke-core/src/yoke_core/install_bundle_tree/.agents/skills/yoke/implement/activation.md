# Implement — Path Claim Activation

Implementation entry activates claims automatically inside
`worktree_preflight.run_preflight` through its `activate_path_claims` helper.
There is one claim/activation/worktree boundary; the engine does not call a
second standalone activation phase.

The implementation-entry target comes from the pinned binding, with effective
path claims enabled and nonterminal claims for the item/actor. Preflight
activates existing claims before it skips lane creation for no-worktree;
claims-off/no-claims is a successful no-op. The declaration gate has already
required coverage when that axis is on.

## State and result

| Initial state | Outcome |
|---|---|
| planned | Resolve integration head, ensure snapshot, activate with events |
| active | Idempotent no-op recorded in outcomes |
| blocked | Report the claim/reason and stop |

The resolver reads the claim's integration target in its own project's
registered checkout, resolves remote then local with explicit divergence
checking, and builds a missing snapshot inline. Activation emits
`PathClaimActivated`; a declaration remains different from acquisition.
Divergence is recorded as `diverged_error`, blocking rows as
`blocked_errors`.

| Exit | Meaning |
|---|---|
| 0 | All selected claims activated or no-op |
| 1 | Blocked claims or diverged refs; surface BLOCKED/DIVERGED narratives |
| 2 | Missing item, owner/source actor, or malformed public ref |

## Operator reconciliation

Normal entry owns activation. For reconciliation outside that bundle, the
registered `claims.path.activation_run` adapter is:

```bash
yoke claims path activation-run --item PREFIX-N
```

Both entry points resolve integration heads from this machine's registered
project checkout before relaying activation, including HTTPS. Register a
missing mapping with `yoke project register <checkout> --project-id <id>`
and retry from that machine.

Exit0 means completed/no claims; exit1 means unresolved checkout/head or
incomplete activation and preserves named outcomes/recovery; exit2 is usage.
Resolve the actual refusal before retry.

Read its `--help` for session overrides and result shape. Never inline a
service-client activation or raw SQL mutation.

A refusal stops before lane creation/status mutation. Follow the actual
dependency direction and attested overlap remediation in the
[claim rules](../../../../.yoke/docs/reference/agent-rules/lanes-and-claims.md);
a coordination-only edge differs from a directional activation dependency.
A diverged integration target needs owner reconciliation preserving local
commits, not an automatic push, pull, rebase or reset. `--force` cannot
override activation. After success, continue the same entry bundle.

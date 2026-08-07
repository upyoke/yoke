# Deploy GitHub status uses a peer control plane

## Decision

When a deployment run needs GitHub Actions status (or any typed GitHub
Actions operation during deploy), it reads through a **peer HTTPS control
plane** that is required to fail independently of the environment under
deploy. It does **not** provision the runner with GitHub App private-key
authority, and it does not derive the same-base sibling of an owner-only
connection (`prod-db-admin` → `prod`).

`deployment-runs create` and `start-for-item` use the same independence
rule on the run-record path: they require an owner-only local-postgres
connection (`*-db-admin` or `local`), not the HTTPS product plane whose
API process may be the deploy target.

## Credential shape (blast radius)

Two shapes reached the circular dependency. This decision picks the second.

1. **Runner-local GitHub App authority** — moves the private key (or an
   equivalent minting secret) onto whatever executes deploys. Blast radius
   widens to every deploy runner and every CI job that could reach that
   secret. Hosted Deploy Relay and CI custody doctrine exist specifically to
   keep runners as clients of a credential-bearing plane, not App hosts.
   Rejected on those grounds.

2. **Peer already-authorized control plane** — runners stay clients. Keys
   stay on control-plane hosts. Status authority is a separately deployed
   HTTPS unit (known pair: `stage` ↔ `prod`). Blast radius unchanged from
   today's App-key custody.

## Independent failure

The peer is a different deployment unit on the release train. Deploying
`prod` reads GitHub through `stage` (and the reverse). A joint outage of
both peers is outside this mitigation; the poll still names the GitHub
Actions UI as the operator surface that answers without either plane.

Same-base sibling derivation (`*-db-admin` → same base HTTPS env) is the
obsolete circular path and is removed. An owner-only env without a known
peer must set `YOKE_GITHUB_ACTIONS_RELAY_ENV` explicitly to an independent
HTTPS plane, or use attended local App authority for bootstrap.

## Create coverage

Create's exposure is control-plane availability for the function call that
writes `deployment_runs`, not App-key minting. Routing create through a
peer HTTPS plane would write to the wrong universe's database. The
surviving authority is owner-only local-postgres against the universe that
owns the run. Refusing HTTPS product create removes the unmitigated path
rather than adding a fallback stack.

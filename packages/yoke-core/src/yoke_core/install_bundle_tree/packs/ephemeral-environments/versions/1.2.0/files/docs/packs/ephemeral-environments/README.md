# Ephemeral Environments Pack

Adds GitHub Actions workflows that build, deploy, list, and remove temporary
branch versions of a FastAPI API and Next.js web app on one Docker host. The
separate Branch Preview Hosting Pack supplies wildcard routing and scheduled
cleanup.

## Project-specific work

- Choose which branches create previews and adjust the workflow triggers.
- Connect SSH secrets and confirm the host has the Branch Preview Hosting Pack
  configured with the same namespace, domain, and port range.
- Reconcile the copied production environment, data volume, health endpoint,
  build contexts, and Compose services with the actual application.
- Decide whether preview data may persist and what teardown must delete.
- Exercise first deploy, fast rebuild, hash collision, branch deletion, and
  expiration against the real application and host.

These workflows are deliberately application-shaped starting points. A project
owns and customizes them after installation.

## Release previews of a frozen candidate

A branch preview follows its branch: every push replaces what the slug
serves, which is exactly what a development preview is for. A release
preview must do the opposite — its URL gets cited as evidence that a
reviewer saw one specific commit, so nothing may move it while that review
is open.

Dispatch `{{project_name}}-ephemeral.yml` with both inputs to deploy one:

- `commit_sha` — the frozen candidate, one full 40-hex commit SHA.
- `yoke_dispatch_id` — the opaque dispatch correlation naming this preview.

They are required together. A candidate with no identity has nowhere to be
published, and an identity with no candidate would publish a frozen preview
of whatever the ref happened to point at.

The preview is published at `rel-<digest>.{{preview_domain}}`, where
`<digest>` is the first 32 hex characters of the SHA-256 of
`yoke_dispatch_id`, hashed whole and with no trailing newline. The
dispatching side derives that URL before this workflow reports one — that is
how it knows where to ask the preview which commit it is serving — so the
two derivations must agree exactly.

That naming is also what keeps the two kinds of preview apart. A branch is
slugified, and slugifying can never produce the `rel-` shape, so no branch
name can land on a release preview's directory, port or URL. Teardown
follows the same rule: pass `yoke_dispatch_id` to
`{{project_name}}-ephemeral-teardown.yml` to remove a release preview, and
`branch_name` to remove a branch one.

### The occupancy guard

Naming alone does not protect a frozen preview, because a slug only says
where a preview lives. `ops/frozen_preview_occupancy.py` decides whether a
given deploy may write there, and the workflows call it rather than
reimplementing the rules in shell:

- **Before any mutation, including the fast path.** A fast-path rebuild
  rsyncs into the same directory, so a check that runs after the write has
  already lost the candidate. The deploy claims the occupancy first or stops.
- **Recorded, not asserted.** `.yoke-preview-owner.json` inside the preview
  directory holds the `yoke_dispatch_id` and `commit_sha` that created it.
  Redeploying the same candidate under the same identity is the ordinary
  retry; a different identity, or the same identity on a different commit, is
  refused. An unreadable record refuses too — unverified is not unoccupied.
- **Cleanup proves ownership.** Teardown refuses an occupancy it cannot show
  it owns. Refusing costs a stale preview; deleting costs the review.
- **Branch previews are untouched.** They claim nothing and prove nothing.
  The one rule that reaches them is the reserved-name refusal, which is what
  keeps them out of the frozen namespace in the first place.

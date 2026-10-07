# Hosted Service Identity

The hosted service (Platform, at upyoke.com) delivers a few facts into each
tenant universe that only it observes: GitHub App installation and repository
lifecycle (`projects.github_binding.lifecycle`) and machine-authorization
expiry or withdrawal (`machine_approval.lifecycle.apply` with state `expired`
or `withdrawn`). It calls as its own least-privilege identity, never as a
person.

## Shape

| Fact | Value |
|---|---|
| Actor | `kind=system`, `system_component=hosted_service` |
| Grant | org role `hosted_service` on the universe's org, and nothing else |
| Permission | `hosted_service.deliver`, org-scoped and service-only |
| Default token name | `hosted-service` |

No human role carries `hosted_service.deliver`: the org `admin` wildcard and
the project `owner` wildcard both exclude it. The role is not offered by member
grants or invites (`actor_grants_cli grant-org`, `identity` invites). Only the
bootstrap below grants it.

## Recognition

A function registered with the `service_token_required` guardrail passes the
HTTP boundary only when the verified token's actor is the active
`hosted_service` system actor holding `hosted_service.deliver`. The token's
name plays no part. Every other caller, including an org admin's
`initial-admin` token, is refused with `permission_denied` and a message naming
this identity and the mint command. A signed-in browser session can never call
these functions.

Dispatch then checks the same permission against the org owning the call's
`payload.project` for `projects.github_binding.lifecycle`. For machine
approvals, the service identity withdraws an `expired`/`withdrawn` request on
its own org without org-admin authority, and the subject-ended contract still
refuses a live authorization. `approved` and `denied` remain member decisions
under the request's org-admin authority.

## Minting and rotation

Platform mints in-process against the tenant database at tenant birth through
`yoke_core.domain.api_tokens.bootstrap_hosted_service_token(conn)`, which
returns the raw token once. Operators use the same operation from the token
CLI:

```bash
python3 -m yoke_core.domain.api_tokens_cli hosted-service \
  [--name hosted-service] [--raw-token-file <owner-only-secret-path>]
```

The actor and its single org grant converge idempotently, and every invocation
mints another active token. If the actor already carries any other grant, the
operation refuses with `hosted_service_identity_not_least_privilege` and names
the grants to revoke.

To rotate a tenant that already runs this identity:

1. Mint a new token.
2. Install it as the tenant's service credential.
3. Verify a delivery.
4. Revoke the superseded token id with `api_tokens_cli revoke --token-id <id>`.

## Moving a tenant onto this identity

An engine without this identity has no role, permission, mint operation, or
guard path for it. It accepts only its `initial-admin` token as the service
credential. An engine with it refuses that token. No single credential passes
on both, so a tenant moves in this order:

1. **Mint ahead, with this build's code.** Run
   `bootstrap_hosted_service_token` from this release's `yoke_core` against the
   tenant database while the tenant still serves its old engine. It only adds
   rows the old engine ignores: the role, its permission, the system actor, its
   org grant, and a token. The old engine keeps serving deliveries with the
   `initial-admin` token.
2. **Swap the credential at pin time.** When the tenant's engine pin moves to
   this release, install the minted token as the tenant's service credential
   in the same step.
3. **Retry inside the window.** Between the new engine starting to serve and
   the swapped credential taking effect, every service delivery fails on one
   side or the other. The new engine refuses the old token with
   `permission_denied`. The old engine refuses the new token, because it is not
   named `initial-admin`. The hosted service retries refused GitHub lifecycle
   and machine-authorization deliveries until the swap completes, so nothing
   delivered in the window is lost.
4. **Retire the old token.** After the first delivery on the new identity
   succeeds, revoke the tenant's `initial-admin` token as a service credential.

The window lasts from the moment the new engine serves until the hosted service
holds the swapped credential. Keep it to the repin step itself.

## What the service may reach

The identity calls only `projects.github_binding.lifecycle` and
`machine_approval.lifecycle.apply`, and only through `/v1/functions/call`.

- Any other function is refused at dispatch, including the baseline every
  signed-in actor gets: minting its own tokens, sessions, decision requests,
  and models.
- Any other HTTP route is refused at authentication with `hosted_service_scope`.
- A disabled service actor is refused like any disabled actor.

A machine-approval `expired`/`withdrawn` delivery from the service succeeds
only when the universe's own rows show the authorization has ended. Either the
expiry stored when it opened has passed by the engine's clock, or the
requesting member has left the org: their actor is disabled, or holds no org
role and no project role there. A delivery about a live authorization is
refused as `hosted_service_withdrawal_subject_live`. An org admin withdraws
one early.

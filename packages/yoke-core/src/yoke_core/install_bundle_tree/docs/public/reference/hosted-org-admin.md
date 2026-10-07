# Hosted org administration from the CLI

On upyoke.com, Platform owns organizations, invites, and machine approvals.
The CLI reaches the same operations the site uses, with the same permission
checks, over a machine's existing hosted connection
(`https://upyoke.com/api/orgs/<slug>`). Platform answers these function ids
itself and never forwards them to the org's universe, so an invite created on
the CLI and one created on the Members page are the same invite, counted
against the same seat limit.

Connect a machine first with `yoke connect https://upyoke.com`. Each command
acts for the person who approved that machine, within the org it connected to.

## Found an organization

```bash
yoke organizations create "Acme Robotics" --slug acme
```

Any signed-in member can found a new org with a redeemed beta code; the founder
becomes its admin. The slug defaults to one derived from the name. Resubmitting
the same slug resumes your own unfinished founding. Refusals:
`beta_grant_required`, `slug_taken`, `invalid_name`, `invalid_slug`,
`provisioning_pending` (resubmit to resume), and `provisioning_failed`. Then
connect a machine to the new org with `yoke connect https://upyoke.com`.

## Invite and revoke

```bash
yoke identity invite create pat@acme.example --role member   # or admin
yoke identity invite list --status pending
yoke identity invite revoke <invite-id>
```

Creating and revoking require the org admin role; any member can list. A hosted
role is `admin` or `member`. Refusals: `hosted_seat_limit_reached` (every seat,
pending invites included, is used; more seats are contact-only),
`duplicate_pending_invite`, `invite_not_pending`, and `not_admin`.

## Approve or deny a machine

```bash
yoke machine-authorization get ABCD-EFGH
yoke machine-authorization resolve ABCD-EFGH --action approve   # or deny
```

The code is the one the connecting machine's CLI printed. An org admin decides
it; the connecting machine then finishes its own poll. Refusals:
`authorization_code_required`, `authorization_unavailable`,
`authorization_expired` (start a fresh connection), and `not_admin`.

## Every surface refuses with its recovery

An org whose plan is not active refuses every call as `org_not_operable`. On a
local or self-hosted universe, `organizations.create` refuses as
`organization_create_hosted_only`: that universe has exactly one org. A hosted
universe's own engine refuses `identity.invite.*` as
`hosted_invites_platform_owned`, because Platform holds hosted invites. On a
self-hosted universe the same `yoke identity invite` commands manage the
server's own sign-in admission.

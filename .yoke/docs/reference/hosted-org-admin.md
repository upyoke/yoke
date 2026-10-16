# Hosted org administration from the CLI

On Yoke Cloud, Platform owns organizations and email invitations. The CLI
reaches the same email invitations as **Team**, with the same permission and
seat checks, over a machine's hosted connection
(`https://app.upyoke.com/api/orgs/<slug>`). The invite-form read and machine
authorization use the org's engine; email invite operations keep their
`identity.invite.*` function ids and are answered by Platform.

Connect a machine first with `yoke setup --connect https://app.upyoke.com`. Each command
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
connect a machine to the new org with `yoke setup --connect https://app.upyoke.com`.

## Invite and revoke

```bash
yoke invite pat@acme.example --role member   # or admin
yoke invites list
yoke invites revoke email-7
```

The invite CLI requires the org admin role, including its form read. A hosted
role is `admin` or `member`. Refusals: `hosted_seat_limit_reached` (every seat,
pending invites included, is used; more seats are contact-only),
`duplicate_pending_invite`, `invite_not_pending`, and `not_admin`.
Use the `email-N` reference from the list. Email invites join through sign-in;
to replace one, revoke it and invite the email again. See
[Teammate invitations](teammate-invitations.md) for both forms and recovery.

## Approve or deny a machine

```bash
yoke machines pending
yoke machines approve K7F2   # or: yoke machines deny K7F2
```

Match the four-character code printed by your connecting machine and check the
approver's displayed identity. An active human member decides their own request;
the connecting machine receives that person's identity and finishes its own poll.
The first decision binds the code to its approver. Refusals include
`authorization_owner_mismatch`, `authorization_already_decided`,
`organization_membership_required`, `actor_disabled`, `authorization_unavailable`
and `authorization_expired` (start a fresh connection). If the server lacks these
commands, connect with `yoke connect <server> --token-stdin` or ask its operator to upgrade.

## Every surface refuses with its recovery

An org whose plan is not active refuses every call as `org_not_operable`. On a
local or self-hosted universe, `organizations.create` refuses as
`organization_create_hosted_only`: that universe has exactly one org. A hosted
universe's own engine refuses `identity.invite.*` and the email-only
`identity.link.set` pre-link as
`hosted_invites_platform_owned`, because Platform holds hosted invites. Use the
hosted invite commands above or the org's Team page. Direct issuer/subject
identity links still work on hosted universes. On a
self-hosted universe the same `yoke invite` and `yoke invites` commands manage the
server's own sign-in admission, attributed to the calling actor; a call with
no numeric actor refuses as `actor_required`.

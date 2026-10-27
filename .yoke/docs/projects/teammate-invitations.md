# Invite a teammate

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Projects](index.md) > Invite a teammate
<!-- /yoke:breadcrumbs -->

From your connected terminal, an organization admin invites a person with
`yoke invite PERSON`. The server chooses the form from its sign-in method:

| Server | Person | How they join |
|---|---|---|
| Self-host without company sign-in | Display name | Redeem a private invite code |
| Self-host with company sign-in | Email address | Sign in with that verified email |
| Yoke Cloud | Email address | Sign in with their Yoke account |
| Local | No teammate invitation | Set up a team server with `yoke self-host init` |

These commands need no project or harness session. They act as the person
attached to your connection. Creating your own API token does not create a
teammate. See [Machine authorization](../cli/machine-authorization.md) to connect
another machine as yourself.

## Create, send and redeem

On a server without company sign-in:

```bash
yoke invite Ana --role operator
```

The result shows Ana's name, the organization role, expiry and the code once.
The default code-invite role is `operator`; self-host roles are `admin`,
`operator` and `viewer`. The code expires after 24 hours and works once.
Copy it now and send it only to Ana through a private channel. Ana runs:

```bash
yoke connect https://yoke.example
```

Then Ana chooses **Enter invite code** and pastes it. This connects Ana's
first machine as Ana. A teammate invite code starts with `yinv_`; a short
machine match code and a beta-access code serve different purposes and cannot
be substituted. Do not send your own API token as a teammate invitation.

With company sign-in or a Yoke account:

```bash
yoke invite ana@example.com
```

The result confirms an email invitation and reveals no code. Tell Ana the
server URL and the sign-in method. Hosted roles are `admin` or `member`.
On self-host, omitting an email invite's role records no role grant; it does
not silently grant `operator`. `--role ROLE` requests an explicit role.

## List, revoke and reissue

```bash
yoke invites list
yoke invites list --include-used
yoke invites revoke code-12
yoke invites reissue code-12
yoke invites revoke email-7
```

Use the exact `code-N` or `email-N` reference from the list. Its Kind column
distinguishes code and email invitations even when their numeric IDs match.
The list shows pending, expired and revoked invitations; `--include-used`
also shows joined invitations. It never reveals stored codes or hashes.

Revoke prevents an unused invitation from admitting a person. Reissue gives
a new code for the same person and invalidates the old code; it also works
for expired or revoked code invitations. Copy the new code immediately.
Email invitations cannot be reissued: revoke their `email-N` reference and
run `yoke invite EMAIL` again. Once a code was used, manage that person's
machines instead of revoking their completed invitation.

## Refusals and recovery

| Reason | Recovery |
|---|---|
| `invite_name_required` / `invite_email_required` | Enter the form named by this server's sign-in method. |
| `invite_local_universe` | Local runs only on this computer; use `yoke self-host init` for a team server. |
| `oidc_misconfigured` | Ask the server operator to correct company sign-in settings. No invitation is created. |
| `function_version_skew` | This server predates this command. Connect with an explicit token (`yoke connect <server> --token-stdin`), or ask the server operator to upgrade. |
| `invite_reissue_email` | Revoke the email reference, then invite the email again. |
| `result_unavailable` | The code cannot be shown again. List the reference and reissue it. |
| `invite_code_invalid` / `invite_expired` / `invite_revoked` | Ask the inviter for a new code; never substitute another kind of code. |
| `invite_consumed` | Manage the person's machines; this invitation was already used. |
| `invite_actor_disabled` / `actor_disabled` | Ask an organization admin to review the person's access. |
| `invite_machine_owned` / `machine_identity_required` | Follow the server's machine-identity recovery before reconnecting. |
| `permission_denied` / `not_admin` | Ask an organization admin to invite the person. |
| `invite_store_unavailable` | Retry when the server's invite store is available; ask its operator if it persists. |

Hosted seat limits and duplicate invitations retain their existing refusals;
see [Hosted org administration](hosted-org-admin.md).

## Structured results

Every command accepts `--json`. The CLI reads `teammate_invites.list` for
`invite_form` and `sign_in_method`, and uses `identity.invite.*` for the email
form. A failed form read is returned directly with no follow-up write.
Hosted email operations remain Platform-owned; code operations use the engine.

Self-host email list rows retain their original fields, including `role_id`,
`invited_by_actor_id` and `created_at`, and add the catalog `role` and
`invited_by_name`. A null role means no role grant. Code rows retain their
reference, kind, actor, name, role, state, expiry and `invited_by`, and include
their own stored `created_at` and `invited_by_name`. Names are the recorded
inviter's trimmed display name, or null when unavailable. Hosted inviter names
come from Platform users; their IDs are not engine actor IDs. Reissue retains
the invited actor and returns the new row's creation time.

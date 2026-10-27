# Team, Billing, Universe settings

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Projects](index.md) > Actors, members and billing
<!-- /yoke:breadcrumbs -->

## Team

Who and what may act on the universe and per project: machine connect,
approvals, tokens. On Cloud, CLI connect and machine authorization start
at the platform routes (`/connect`, `/machine`).

The dashboard's **Team** page reads the live actor roster in two groups:
**People** (human actors) and **Machine accounts** (system actors). Each row
shows the actor's active or disabled state and its API keys: a key count
and the most recent use (UTC time and machine name). Expanding the count
lists every unrevoked key by name, ID, last use, and machine association;
an actor with none reads **No active keys**. A person's row also shows
their org role and **Project access**: every org role reaches every project
in the org, so access starts with `All projects · from org <role>`, then
each project grant as `<project> · <role>`, with the role styled as a role
and its description on hover. A machine account's row has one **Grants**
column listing each org and project grant with its scope (`Org` or
`Project · <project>`), its role, a `machine-only` tag for roles only
machine credentials hold, a `bootstrap-granted` tag for a role only its own
bootstrap grants (`hosted_service`), and what the role allows. The roster
read serves these role descriptions and role sets, so the page copies no
role prose. Hosted
mode adds a **Member email** column to People: the linked sign-in email when
one exists. Disabled actors are hidden by default; **Show disabled (N)** in
the People header names how many are hidden and reveals them. Every column but Action sorts from its
header, and the chosen sort is saved to your actor's preferences under the
actor roster, the same store the Items table uses, so it follows you across
tabs, browsers, and reloads rather than staying in one browser. An org admin
can disable or enable a human actor other than themselves. The last active
org admin cannot be disabled. A retired system actor can be disabled through
`yoke actors state set ACTOR-ID --disable --confirm-system-retirement` after
checking its live workflow and service references. A deployment actor with an
active deployment credential
must have its release dependency retired and credential revoked first.
Disabling immediately blocks
the actor's browser sessions and other authority and revokes all its API keys,
including machine keys. Enabling restores role access but does not restore
those keys: the person must sign in again and reconnect affected machines.
A local universe has no Invites panel. Its notice, headed **Set up a team
server to add people**, names `yoke self-host init`; with one human actor it
also says you are the only actor.

Org admins use **Invite** in the Team page head. The server selects the form:

| Universe | Invite field | How the teammate joins |
|---|---|---|
| Local | No Invite action | This universe is reachable on this computer only. Set up a team server with `yoke self-host init` to share it. |
| Self-hosted without company sign-in | Name and org role | Send the one-time invite code privately. The teammate runs `yoke connect <server>` and chooses **Enter invite code**. |
| Self-hosted with company sign-in | Email and org role | The teammate signs in with their own company identity. |
| Cloud | Email and org role | The teammate signs in with their own Yoke account. |

The role defaults to `operator`; its description comes from the roster.
A matching name warns that another person will be created. A code invite
creates an active person immediately and stays pending until redemption.
Its code appears once, expires in 24 hours and works once. Send it only to
that person through a private channel. **Done** or leaving Team removes the
code; Yoke keeps only its hash. An email invitation shows a sent confirmation
without a code.

The **Invites** panel sits above People and shows each person, invite kind,
role, state, expiry and inviter. On Cloud, when the viewer can invite, its
header also shows **· N seats left** and the invite form adds **This invite
uses 1 of N seats left.** At zero the form instead says **No seats left.
Change plan in Billing, or revoke a pending invite.** Pending, expired, revoked and joined rows are grouped in that order,
with newest creation time first within a group. **Show used** reveals joined
rows. An explicit empty role grant is shown as **No role grant**. Older servers
with incomplete fields show unavailable/upgrade information, never inferred
roles, creation times or inviter identities.

An admin can **Revoke…** a pending invite or **Reissue** a pending, expired or
revoked code invite after confirmation. Reissue creates a new code for the
same person and invalidates the old code. To resend an email invitation,
revoke it, then invite again. A lost code or an unavailable replay result
also needs Reissue. These actions refresh the roster and invites while
keeping the visibility toggles and any displayed result until Done.
Other members see the list without invite actions. A failed invite read
leaves the roster usable; **Try again** repeats the read. Registry/version
refusals request a server upgrade, and a company sign-in configuration refusal
names the server operator recovery. See [teammate invitations](../projects/teammate-invitations.md).

Each person holds exactly one org role, and the engine owns it in every mode —
local, self-hosted, and Cloud alike:

| Org role | What it allows |
|---|---|
| `admin` | Administer the org and every project in it. |
| `operator` | Normal Yoke work across every project in the org. |
| `viewer` | Read items and events. |

An org admin changes a person's role from the role control in the Team
roster, or with `yoke actors role set ACTOR-ID --role ROLE` (or
`--member EMAIL` to name the person by the email they sign in with). The new
role replaces the old one. The change is refused, with the reason named,
when it would demote the last active admin (make someone else admin first),
when the role is machine-only (`deployment_ci`, `hosted_service`,
`infrastructure_ci`, `migration_verification_ci` belong to machine
credentials), when the role is
not one of the three above, or when the actor is a system actor. An email
with no linked actor is refused until that person signs in once. Project
roles (`owner`, `operator`, `viewer` on one project) remain separate grants.

Disable opens a confirmation naming the actor and stating that its API keys
will be revoked. Cancel changes nothing; a failed confirmation remains retryable.
On narrow screens the roster becomes labeled cards, retaining the first actor
and every access fact.

Use **Machines** to approve a request after comparing its machine, code,
organization and deciding identity. Approval grants only the approving person's
identity. Approve your own machines; a teammate must join with their own invite.
The workbench's **Connect your machine** page uses the same engine-owned
decision and one-time credential delivery in Cloud and self-hosted mode.

On Cloud the roster also shows the hosted service's own system actor,
`hosted_service`, holding only the `hosted_service` org role. It delivers
GitHub App lifecycle changes, machine-code handoff and polling after organization selection,
and machine-authorization expiry or withdrawal. See the
[hosted handoff contract](../cli/machine-authorization.md#hosted-code-handoff). No member or admin token can stand in for it, including the
universe's first `initial-admin` token.

## Seats and membership (Cloud)

Team is the one people destination in every mode. On Cloud, Platform's seat
section leads the Team page, above Invites; there is no separate Members
page, and a `/members` link opens Team. Local and self-hosted Team pages
have no seat section.

Membership admission adopts the person's account name for cards, boards and
events. Account renames sync on the next membership update without changing
actor IDs, claims, roles, tokens or linked identities; equal names do not merge
people. An unnamed account leaves the actor's existing name unchanged.
Actors without a member link keep their names. This never waits on Platform:
an unreachable Platform leaves a stale name instead of returning an error.

## Billing (Cloud)

Platform-fed. Plan and payments. Local and typical self-host shells omit or
stub this.

## Universe settings

Organization / universe level: export/import portability, founding new orgs
(Cloud), and other universe-scoped controls. Project settings stay under
**Project settings**.

## Local, Self-hosted, and Cloud cheat sheet

| Concern | Local | Self-hosted | Cloud |
|---|---|---|---|
| Workbench | `yoke ui up` | `yoke ui up`: company sign-in or a single-use token link | app.upyoke.com |
| Seats / Billing | N/A | N/A | Team seat section; Billing page |
| Team invitations | Unavailable; reachability notice | Name/code or company email, as reported by the server | Email invitation |
| Machine approval | N/A (you are the machine) | Connect, then approve your own machine from the printed link or Machines | Machines page / connect |
| Universe export | Yes | Yes | Yes (portability) |

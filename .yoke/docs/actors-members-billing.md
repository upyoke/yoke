# Actors, Members, Billing, Universe settings

## Actors

Who and what may act on the universe and per project: machine connect,
approvals, tokens. On Cloud, CLI connect and machine authorization start
at the platform routes (`/connect`, `/machine`).

The dashboard's **Actors** page reads the live actor roster in two groups:
**People** (human actors) and **Machine accounts** (system actors). Each row
shows the actor's active or disabled state, organization role, project
grants as `project (role)` — `all projects` for an org admin — and every
unrevoked API key by name, ID, last use, and machine association. Hosted
mode adds a **Member email** column to People: the linked sign-in email when
one exists. Disabled actors are hidden by default; **Show disabled (N)** names
how many are hidden and reveals them. Every column but Action sorts from its
header, and the chosen sort is saved to your actor's preferences under the
Actors screen, the same store the Items table uses, so it follows you across
tabs, browsers, and reloads rather than staying in one browser. An org admin
can disable or enable a human actor other than themselves. The last active
org admin cannot be disabled. A retired system actor can be disabled through
`yoke actors state set ACTOR-ID --disable --confirm-system-retirement` after
checking its live workflow and service references. The canonical core actor
cannot be disabled. A deployment actor with an active deployment credential
must have its release dependency retired and credential revoked first.
Disabling immediately blocks
the actor's browser sessions and other authority and revokes all its API keys,
including machine keys. Enabling restores role access but does not restore
those keys: the person must sign in again and reconnect affected machines.
A local universe with one human actor says you are the only actor.

Disable opens a confirmation naming the actor and stating that its API keys
will be revoked. Cancel changes nothing; a failed confirmation remains retryable.
On narrow screens the roster becomes labeled cards, retaining the first actor
and every access fact.

A machine waiting to be admitted is answered on the **Machines** page,
not here: approving needs the machine beside the decision — which one,
who asked for it, and the one-time code the person at that machine is
reading. Approving admits the machine and nothing more. The machine
belongs to the actor who installed Yoke and authenticated on it, so an
admin answering for someone else never becomes its owner.

Self-hosted users approve their own code on the workbench's **Connect your machine**
page. Approval binds the new machine and credential to that signed-in actor.
The existing org-admin approval path on Cloud retains its authority.

On Cloud the roster also shows the hosted service's own system actor,
`hosted_service`, holding only the `hosted_service` org role. It delivers
GitHub App lifecycle changes and machine-authorization expiry or withdrawal,
and nothing else. No member or admin token can stand in for it, including the
universe's first `initial-admin` token.

## Members (Cloud)

Platform-fed. People in the organization, seats, invites. Not present as a
product concern in pure local mode.

A member's account name is what the universe calls them. Each membership
admits its person through the universe's own sign-in ladder, and that
admission adopts the account's name as the actor's name — so cards, boards,
and events show the person, not a GitHub handle. A rename on the account
propagates on the member's next sync and moves nothing else: the actor id
stays the same, so its claims, roles, tokens, and linked identities are
untouched, and two members who genuinely share a name stay two members. An
account with no name of its own changes nothing, and the actor keeps the
name it already had. Actors with no member link at all — local universes,
self-hosted installs, an organization never connected — keep their names
untouched, and nothing here waits on the platform: an unreachable platform
leaves a name stale, never an error.

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
| Members / Billing | N/A | N/A | Platform sections |
| Machine approval | N/A (you are the machine) | Company sign-in → approve your own machine at `/machine-approval`; API token when OIDC is absent | Machines page / connect |
| Universe export | Yes | Yes | Yes (portability) |

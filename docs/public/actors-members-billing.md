# Actors, Members, Billing, Universe settings

## Actors

Who and what may act on the universe and per project: machine connect,
approvals, tokens. On Cloud, CLI connect and machine authorization start
at the platform routes (`/connect`, `/machine`).

A machine waiting to be admitted is answered on the **Machines** page,
not here: approving needs the machine beside the decision — which one,
who asked for it, and the one-time code the person at that machine is
reading. Approving admits the machine and nothing more. The machine
belongs to the actor who installed Yoke and authenticated on it, so an
admin answering for someone else never becomes its owner.

## Members (Cloud)

Platform-fed. People in the organization, seats, invites. Not present as a
product concern in pure local mode.

A member's account name is what the universe calls them. Each membership
admits its person through the universe's own sign-in ladder, and that
admission adopts the account's name as the actor's display label — so cards,
boards, and events show the person, not a GitHub handle. A rename on the
account propagates on the member's next sync; an account with no name of its
own changes nothing, and the actor keeps its existing fallback (its system
component, then its GitHub label). Actors with no member link at all — local
universes, self-hosted installs, an organization never connected — keep that
same fallback chain untouched, and nothing here waits on the platform: an
unreachable platform leaves a name stale, never an error.

## Billing (Cloud)

Platform-fed. Plan and payments. Local and typical self-host shells omit or
stub this.

## Universe settings

Organization / universe level: export/import portability, founding new orgs
(Cloud), and other universe-scoped controls. Project settings stay under
**Project settings**.

## Local vs Cloud cheat sheet

| Concern | Local | Cloud |
|---|---|---|
| Workbench | `yoke ui up` | app.upyoke.com |
| Members / Billing | N/A | Platform sections |
| Machine approval | N/A (you are the machine) | Machines page / connect |
| Universe export | Yes | Yes (portability) |

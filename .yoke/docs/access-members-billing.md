# Access, Members, Billing, Universe settings

## Access

Who and what may act on the universe and per project: machine connect,
approvals, tokens. On Cloud, CLI connect and machine authorization flow
through platform routes (`/connect`, `/machine`) and the Access section.

## Members (Cloud)

Platform-fed. People in the organization, seats, invites. Not present as a
product concern in pure local mode.

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
| Workbench | `yoke ui` | app.upyoke.com |
| Members / Billing | N/A | Platform sections |
| Machine approval | N/A (you are the machine) | Access / connect |
| Universe export | Yes | Yes (portability) |

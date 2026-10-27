# Hosting modes

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Hosting modes
<!-- /yoke:breadcrumbs -->

Your Yoke Universe is the shared home for projects, strategy, work records, and configuration. Choose where its core service and database run; your coding agents can continue running on your own machines.

<!-- yoke:visual hosting -->

## Universes and where they live

A Universe contains projects. A project contains its direction, work, and configuration. A checkout is a folder containing code on a particular machine; several checkouts can connect to the same project.

A connection tells the CLI which Universe to use and which identity it acts as. Changing connections changes the Universe you are working with; it does not move its data or change the repository's contents.

## Local

Local mode runs the core and embedded PostgreSQL on your computer without a hosted signup. It is reachable on that computer only. The machine relay supports local session launches and liveness reporting, and `yoke ui up` opens the dashboard.

Local mode is appropriate when one machine holds your work. To connect other machines or teammates, use self-hosted or hosted mode and move the Universe through export and import. Simply exposing a local dashboard port is not the team-server setup.

## Self-hosted

Self-hosted mode runs the core and PostgreSQL on infrastructure you control. Your other machines connect to the server, and each person's agents work against the same Universe.

You manage the server, networking, updates, and backups. Guided setup can create the server bundle, but it does not configure your VPN, DNS, reverse proxy, or TLS. See [Self-hosting](self-hosting.md).

## Hosted

Yoke hosts and updates your Universe. Sign in at [app.upyoke.com](https://app.upyoke.com); access is currently private beta. You connect your own machines and coding harnesses, with their model credentials.

Hosted membership, seats, and billing are managed through the hosted service. These platform features do not apply to local or self-hosted Universes.

## Connections across machines

Run setup on each machine and connect it to the intended Universe. Approve your own machine through the sign-in or machine-authorization flow. Teammates join under their own identities rather than sharing your API token.

`yoke status` reports the selected connection. Agents can inspect configured connections and switch intentionally when needed. A relay belongs to its connection and machine; a connected machine does not automatically make every harness signed in or available.

See [Team collaboration](access.collaboration.md) and [Yoke CLI and relay](cli-relay.md).

## Universe portability: export and import

Export and import let you move a Universe between hosting modes without recreating its strategy or backlog. A Universe archive carries database records, not repository folders, application databases, or every external artifact.

Import replaces the destination Universe and requires reconnecting credentials and machines. See [Universe portability, backup, and restore](universe-portability.md) before planning a move.

For mode-specific commands and constraints, see the [hosting reference](../start/modes.md).

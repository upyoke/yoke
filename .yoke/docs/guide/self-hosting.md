# Self-hosting

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Self-hosting
<!-- /yoke:breadcrumbs -->

Self-hosting gives your team a shared Yoke Universe on a server you manage. Yoke provides the core service and database bundle; you provide a reachable server, access controls, updates, and backups.

## Server prerequisites and installation

Start with [Installation and setup](setup.install.md), choosing **Host a server here** on the server machine. Guided setup previews the bundle location, port, Docker requirement, and networking responsibilities before applying changes.

The server bundle lives outside your project checkout. It contains Yoke's core and PostgreSQL services and establishes the first administrator. Reusing an existing bundle restarts that installation rather than creating another Universe.

The operator command is `yoke self-host init`. Use its help and the [self-hosting reference](https://github.com/upyoke/yoke/blob/main/docs/self-host.md) for deployment-specific flags.

## Start the Yoke core and database

Guided setup starts the Compose bundle, waits for the server to answer, and establishes the host's connection. Keep the bundle's configuration and database storage together when administering the server.

A core service that answers a health request is not the same as a machine with a working authenticated connection. Check the server and the client separately when investigating an installation problem. See [Health and readiness](../verification/health-readiness.md).

## Networking, HTTPS, and server access

The default server binding is loopback-only. For another machine to connect, publish a reachable private address or place the service behind an HTTPS reverse proxy. Setup does not create a VPN, open router ports, or arrange a public domain for you.

Public connections require HTTPS. Private HTTP is permitted for supported private addresses, with a warning that machine tokens travel without transport encryption; use a trusted encrypted network or HTTPS. Docker-published ports can bypass host firewall rules, so configure the actual network boundary rather than assuming a local firewall is enough.

When using a reverse proxy, declare trusted proxy addresses and preserve the required forwarded host and protocol information. The detailed [mode reference](../start/modes.md#self-hosted) covers the supported settings.

## Authentication and machine connections

On another machine, choose **A team server** during setup and enter the server URL. Company sign-in can be configured with OIDC. Without it, the supported token and machine-approval flows establish the connection.

To add a teammate, invite that person with their own identity. To add another machine for yourself, approve it as yourself. These are separate actions: sharing your own token does not create a teammate.

Run `yoke ui up` in your Terminal on a connected machine to open the dashboard. With company sign-in it opens that flow; otherwise Yoke opens a short-lived browser sign-in link for the connected actor. See [Team collaboration](access.collaboration.md) and [Machine authorization](../cli/machine-authorization.md).

## Updates, restarts, and health checks

The server operator owns server updates. `yoke self-host upgrade` updates the supported packaged installation; source-checkout installations follow their source-development path instead. Follow the command's reported checks and recovery rather than replacing a live bundle manually.

After an update, check that the server is healthy, the intended Universe is selected, and connected machines can authenticate. Session or relay problems may be local to a worker machine even when the server is healthy.

See [Operations and troubleshooting](operations.md) for Doctor, logs, and connection diagnostics.

## Backup and recovery

The bundle keeps database data in its `pgdata` volume and server machine state, pause markers, and locally stored artifacts in `corestate`. Preserve both volumes across container replacement. After updating an older bundle, run `yoke self-host init --protect-existing --start` with the updated CLI before exporting a paused move.

Keep portable Universe backups outside the server's own storage and validate them before relying on them. Import replaces the selected destination, so verify the target and preserve any data you need first.

A Universe backup does not replace backups of repositories, application databases, or external artifact storage. See [Universe portability, backup, and restore](universe-portability.md).

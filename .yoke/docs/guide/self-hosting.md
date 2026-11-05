# Self-hosting

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Self-hosting
<!-- /yoke:breadcrumbs -->

Self-hosting gives your team a shared Yoke Universe on infrastructure you manage. Yoke supplies the core service and PostgreSQL bundle; you own the host, network access, updates, and backups.

## Install and operate the server

The bundle lives outside project checkouts and creates the first administrator. Guided setup can create it on the server machine; manual installation offers the same bundle. Choose loopback access for a proxy on the host, a private address for a trusted network, or HTTPS for public access.

[Install and run](../self-hosting/install.md) covers Docker prerequisites, macOS runtimes, networking, server automation, upgrades, recovery, and removal. Preserve the database and server-state volumes when replacing containers.

## Choose browser admission

The web dashboard runs at the server's own origin. Without company sign-in, a connected person's CLI opens a short-lived sign-in link. With OpenID Connect (OIDC), the server uses your company's identity provider. Both paths act with the signed-in person's permissions.

[Browser sign-in](../self-hosting/browser-sign-in.md) explains admission choices, trusted proxies, cookie protection, and company sign-in configuration.

## Connect people and machines

Each teammate needs their own identity. Approving another machine for yourself is separate from inviting a teammate; sharing your own token does not create another person.

[People and machines](../self-hosting/people.md) covers invitations, personal machine approval, and token creation and revocation.

## Protect and move the Universe

Keep portable backups outside the server and verify the destination before replacing its data. Universe backups carry Yoke records and included artifacts; repositories, application databases, and external storage need their own protection.

[Universe portability, backup, and restore](universe-portability.md) covers archive validation, source pause, import, and reconnection. [Operations](operations.md) covers health checks and diagnosis.

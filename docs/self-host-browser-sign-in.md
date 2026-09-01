# Browser Sign-In for a Self-Hosted Yoke Server

An optional door on the server described in [Self-Host Yoke](self-host.md).
Leaving it unconfigured changes nothing for tokened clients.

Optionally, the server can offer a browser sign-in door backed by your
identity provider — anything that speaks OpenID Connect with discovery
(Okta, Keycloak, Microsoft Entra ID, Google Workspace, ...). Browser
sessions are deliberately **read-only**: a signed-in browser sees the
landing page; every write still requires an API token over
`Authorization: Bearer`. Leaving the door unconfigured changes nothing
for tokened clients — the OIDC routes simply answer 409.

**1. Register a client at your provider.** Create a confidential "web
application" client with the authorization-code flow, scopes
`openid email profile`, and this redirect URI (your server's external
base URL plus the fixed callback path):

```text
https://yoke.internal/v1/auth/oidc/callback
```

**2. Wire the bundle.** In the bundle directory, write the client
secret as an owner-only file and enable the commented blocks:

```bash
printf '%s\n' '<client-secret>' > secrets/oidc-client-secret
chmod 600 secrets/oidc-client-secret
```

Then uncomment the OIDC lines in `.env` (`YOKE_OIDC_ISSUER`,
`YOKE_OIDC_CLIENT_ID`, `YOKE_OIDC_REDIRECT_URL`,
`YOKE_OIDC_CLIENT_SECRET_FILE`) and the two `yoke-oidc-client-secret`
blocks in `docker-compose.yml`, and `docker compose up -d`. Setting
some vars but not all fails loudly: the door answers 409 naming what is
missing.

The Compose service mounts the owner-only source secret as root, copies it into a container-private tmpfs as mode `0600` owned by the image's `yoke`
user, rewrites the file binding, seals the original mount directory as
root-only, clears supplementary groups, and drops to that user before starting
the server. Every source must be a read-only mount; this also handles Compose
implementations that normalize the in-container source-file mode. The same
bootstrap protects the core database DSN and optional GitHub App key; host
copies remain owner-only.
Compose drops every ambient container capability, grants only the three needed
for this handoff (`CHOWN`, `SETGID`, and `SETUID`), enables
`no-new-privileges`, and the bootstrap refuses to start the server if any
effective Linux capability remains after the drop. The Compose healthcheck
uses the same immediate drop, so the service-level root override does not leave
periodic root healthcheck processes running beside the server.

**3. Decide who gets in.** Visiting `https://yoke.internal/` offers
"Sign in"; after the provider round-trip the server admits the verified
identity by the first matching rule:

1. **Already linked** — the identity (issuer + subject) was linked to an
   actor by a previous sign-in or an admin pre-link.
2. **Pending invite** — a pending invite matches the verified email
   (case-insensitive); accepting it links the identity and grants the
   invite's org role, if one was set.
3. **Verified-domain membership** — a verified email matching the enabled org domain creates a member actor without a role grant.
4. Otherwise the sign-in is **refused** with an operator-facing reason.

Admission administration is org-admin surface on the `yoke` CLI:

```bash
yoke identity invite create pat@corp.example --role admin
yoke identity invite list --status pending
yoke identity invite revoke <invite-id>
yoke organizations domain set corp.example  # or: --clear
yoke organizations settings merge --set membership.auto_join_domain_verified=true
yoke identity link set --actor <actor-id> --issuer <iss> --subject <sub>
yoke identity link set --actor <actor-id> --email pat@corp.example
```

Email trust is strict by default: invites and domain membership match only when
the provider marks the email verified. For providers that omit the
`email_verified` claim entirely, opt in with
`YOKE_OIDC_ALLOW_UNVERIFIED_EMAIL=true` (an explicit `false` from the
provider is never trusted).


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
`YOKE_OIDC_CLIENT_SECRET_FILE`), then run
`yoke self-host init --dir PATH --protect-existing --start`. Setting
some vars but not all fails loudly: the door answers 409 naming what is missing.

The host operator opens the mode `0600` client secret and streams it through
Docker exec stdin. After receiving the inputs privately, the bootstrap clears
supplementary groups and drops to the image's `yoke` user, which writes private
mode `0600` copies in tmpfs before starting the server. Host files are never
mounted or chowned. The same handoff protects the database DSN and GitHub App key.
Compose drops every ambient capability, grants only `SETGID` and `SETUID`, and
enables `no-new-privileges`. Bootstrap and healthchecks prove the runtime has
no effective Linux capabilities after the drop. Restart through the same host
command so it can reopen the inputs; automatic restart is disabled.

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


# Browser Sign-In for a Self-Hosted Yoke Server

Browser admission on the server described in [Self-Host Yoke](self-host.md).
Company sign-in is optional; API-token clients work with either choice.

The server serves the universe workbench at its own URL — the same
workbench Local and Cloud serve. Run `yoke ui up` on a connected CLI to open it.
A signed-in browser works with **full read and write** as its own
actor: the workbench calls `POST /v1/functions/call` with the session
cookie, and the engine's per-actor permission model decides what that
actor may do, exactly as for an API token.

**Without company sign-in.** `yoke ui up` exchanges the CLI's API token for a
single-use link valid for two minutes. The server stores a public selector and
the SHA-256 hash of its secret, compares the hash in constant time, and consumes
it atomically when minting a normal browser session for the token's actor.
The secret travels in a URL fragment and same-origin POST body; it is removed
from browser history before redemption and is never a request URL. Treat the
link printed in the terminal (or `private_url` with `--json`) like a password.
Expired, used, or invalid links name `browser_sign_in_expired`,
`browser_sign_in_used`, or `browser_sign_in_invalid` and tell you to run
`yoke ui up` again. Actor disablement also blocks redemption. `--no-browser`
prints the link without opening it. The signed-out page teaches this CLI path.

**With company sign-in.** `yoke ui up` opens the server's own URL, and the
OIDC admission ladder below applies. Token-link minting and redemption are
disabled, including links minted before OIDC was enabled. Any partial OIDC
configuration fails by name rather than falling through to token sign-in.
The CLI discovers this method without an API token; company sign-in remains
reachable even when the machine's token needs replacing.
Providers can be anything that speaks OpenID Connect with discovery:
Okta, Keycloak, Microsoft Entra ID, Google Workspace, and others.

**What protects the cookie.** The session cookie is `HttpOnly` and
`SameSite=Lax`, so browsers do not attach it to cross-site writes. Every
cookie-authorized call must also be same-origin: a present `Origin` must
name the server's own host (`X-Forwarded-Host` first, then `Host`, so set
it in your reverse proxy), and a present `Sec-Fetch-Site` must be
`same-origin` or `none`. Anything else is refused as
`cross_origin_refused`. A request carrying `Authorization: Bearer` is
authenticated by its token, never by a cookie riding along. The browser
identity also counts as "a person at a browser" for decisions only a
person may take, such as clearing a merge-candidate review from the Inbox.
Token-link redemption enforces the same Origin and Sec-Fetch-Site checks.
Cookies are Secure on HTTPS; use TLS for remote access and configure trusted
proxy forwarding so the server sees the external HTTPS scheme.

The workbench, its `/assets/` roster, and `/served-build` (the commit the
server serves, read by browser QA) are served at the server's site root,
so expose the server at a host root rather than under a path prefix.

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

**3. Decide who gets in.** Visiting `https://yoke.internal/` (or any
workbench page) signed out offers "Sign in"; after the provider round-trip
the server admits the verified identity by the first matching rule and
opens the workbench for that actor:

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


## Connect your own machine

With company sign-in configured, run `yoke connect https://<server>` or choose
**A team server** in `yoke setup`. Open the printed approval link, sign in,
compare its one-time code with your CLI, and select **Approve my machine**.
Sign-in returns you to that workbench page. The CLI receives a machine-bound
credential once and verifies it before saving the connection. Org membership
is required; approving your own machine does not require an org-admin role.

Codes expire after ten minutes. A denied, consumed, or expired code requires a
fresh connection. A temporary credential-store failure remains retryable while
the code is live. Without OIDC, use an explicit API token; the first-boot admin
token remains the bootstrap. See [Machine authorization](public/reference/machine-authorization.md).

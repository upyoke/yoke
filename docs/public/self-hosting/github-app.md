# GitHub App server automation

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Server GitHub App
<!-- /yoke:breadcrumbs -->

GitHub automation uses an operator-owned App and key dedicated to the self-hosted
server, never an upyoke Product App or Yoke Development. Configure its URLs on the
server's HTTPS origin. Project rows store verified installation/repository
bindings; the App private key is never stored in `capability_secrets` or any
per-project setting.
Before creating the runtime key file, register a dedicated App, review its [repository permissions](../github/permissions.md), and establish your key-rotation and incident-response procedure. Never share its private key with engineer machines.
When the same App also serves engineer-machine authorization, enable **Device
Flow** and **Expire user authorization tokens** in its registration before
connecting any machine. The first enables browser device authorization; the
second supplies the expiring access token, refresh token, and expiries that the
local credential store requires. Use the [baseline repository grant](../github/permissions.md#baseline-requested-of-every-connection).
Install the downloaded App private key through Yoke's owner-only ingress. From
outside the bundle, run:

```bash
chmod 600 /secure/path/app-key.pem
yoke self-host init --dir /path/to/yoke-server --protect-existing \
  --github-app-private-key /secure/path/app-key.pem
```

The source must be a real, single-link regular file owned by the current user
with no group/world access. The command opens it once without following
symlinks, validates a nonempty private-key-shaped PEM, writes a mode `0600`
temporary file in the bundle's `secrets/` directory, fsyncs it, atomically
replaces `github-app-private-key.pem`, and fsyncs the directory. Rotation never
publishes a partial key and never regenerates the bundle's database credentials.
Then set these non-secret/runtime bindings in `.env`:

```text
YOKE_GITHUB_APP_ISSUER=<numeric-app-id>
YOKE_GITHUB_APP_API_URL=https://api.github.com
YOKE_GITHUB_APP_PRIVATE_KEY_FILE=/dev/shm/yoke-runtime-secrets/yoke-github-app-private-key

# Optional product-facing Connect GitHub profile; set all four or none.
YOKE_GITHUB_APP_WEB_URL=https://github.com
YOKE_GITHUB_APP_ID=<numeric-app-id>
YOKE_GITHUB_APP_CLIENT_ID=<public-client-id>
YOKE_GITHUB_APP_SLUG=<app-slug>
```

Enable the file binding in `.env`, then run `yoke self-host init --protect-existing --start`. The
GitHub App is disabled until all three values and the host key
are present. GitHub Enterprise Server uses its HTTPS API origin in
`YOKE_GITHUB_APP_API_URL`; redirects to another origin are rejected.
The key stays mode `0600` in the host bundle. The host command opens it and
streams it to the bootstrap alongside the database DSN and optional OIDC secret.
The runtime user writes mode `0600` copies in private tmpfs after the privilege
drop; host ownership and modes stay unchanged.

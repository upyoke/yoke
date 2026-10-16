# People and machines on your server

Each engineer installs Yoke, then connects to your server:

```bash
curl -fsSL https://upyoke.com/install | sh
yoke connect https://yoke.internal
```

The connecting terminal shows a four-character **Match code**, such as `K7F2`.
On one of your machines already connected to this server, run:

```bash
yoke machines pending
yoke machines approve K7F2
```

Check the machine and code, and read the signed-in identity shown before the
decision: the new machine will act as that person. Approve only your own machine.
To refuse the request, run `yoke machines deny K7F2`. Codes accept either case.
The workbench offers the same personal decision under **Machines → Waiting for
approval**. Return to the connecting terminal for one-time credential delivery,
then run `yoke status`. An expired code or lost delivery requires a fresh connect.

`yoke machine …` manages machines already registered to the server, and
`yoke machines …` lists, approves and denies machines waiting to connect.

With company sign-in (OIDC), sign in on the workbench to approve your first
machine. The setup wizard's **A team server** option discovers that sign-in
method after you enter the server URL.

Without company sign-in, a teammate's first machine connects with a pasted API
token or token file: `yoke connect https://yoke.internal --token-stdin` or
`--token-file PATH`. The first-boot admin token remains the bootstrap; an admin
can mint other API tokens on the host with
`docker compose exec --user yoke core python3 -m yoke_core.domain.api_tokens_cli mint --actor <actor-id> --name <engineer-label>`.

For an explicit token for your own identity, use your connected terminal:

```bash
yoke tokens create --name ci
yoke tokens list
yoke tokens revoke TOKEN-ID
```

Copy the new token now; it is shown once. Lost it? List its ID, revoke it, and
create a new one. These commands need no project or harness session. Use the
token with `yoke connect https://yoke.internal --token-stdin` or `--token-file PATH`.
The token acts as you; it does not create a teammate or give them their own identity.
Profile → API tokens → **New token** offers the same creation and recovery.

A local universe runs only on its computer and cannot connect teammates or a
second machine. `yoke machines pending` explains this instead of showing an empty
list; set up a team server with `yoke self-host init` when you need shared access.
If a server predates the admission commands, connect with an explicit token
(`yoke connect <server> --token-stdin`) or ask its operator to upgrade.

Use HTTPS for network servers (numeric loopback HTTP is permitted locally).
The connection is saved only after `/v1/health` and `/v1/auth/identity` pass.
See [Machine authorization](public/reference/machine-authorization.md) for
expiry, retry, and single-use credential delivery.

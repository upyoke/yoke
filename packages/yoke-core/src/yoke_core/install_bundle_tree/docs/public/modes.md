# Modes

One installer. After install, choose where the Yoke core and its database live.

## Local

Private on your machine. No signup. One human, as many agents as you want.

- Wizard: pick **This machine**, or run `yoke init --local`
- Data under `~/.yoke/`
- The machine relay is installed here too, so the workbench sees which harnesses
  this machine can start, reports session liveness, and can launch and resume
  sessions. It runs your installed Yoke and needs no account or API token.
  macOS uses a LaunchAgent; Linux uses a systemd user service that stops at
  logout without linger. See [Linux relay supervision](reference/linux-relay.md).
- Open the workbench with `yoke ui up` (detached; `yoke ui` reports it, `yoke ui down` stops it)
- Members and Billing tabs do not apply (Cloud-only platform features)

Portable: `yoke universe export` dumps the universe; import it later into
self-hosted or another local machine.

Local browser function calls to `POST /api/functions/call` require an object
in `payload`, just like the self-hosted workbench. Omit it or send `{}` for
an empty payload. `null`, lists (including key/value pairs), strings, numbers,
and booleans receive HTTP 422 `envelope_invalid` with recovery text before
dispatch.

## Yoke Cloud

Hosted core at upyoke.com. Collaborate from the web dashboard.

- Wizard: pick **upyoke.com**
- Sign-in, beta-code redemption, org founding, and machine approval happen in
  the connect step
- Private beta: seats and tenant attached to the code; bring your own workers
  and model credentials
- Members and Billing are platform-managed sections in the workbench

Hosted cores serve through the same trusted-proxy boundary as self-hosted
ones: only transport peers listed in `YOKE_API_TRUSTED_PROXIES` (explicit
IPs/CIDRs, never `*`) may supply `X-Forwarded-Host`, `X-Forwarded-Proto`, and
`X-Forwarded-For`. The hosted platform declares its relay peers there, so
origin-checked routes compare `Origin` against the public host rather than the
engine's upstream address.

## Self-hosted

Run Yoke core and Postgres on your own server.

Open its workbench with `yoke ui up` on a connected machine: company sign-in
opens the server URL; without OIDC, the API token gets a single-use browser
sign-in link valid for two minutes. Rerun the command if the link expires.

- Wizard on the host: pick **Set this machine up as a self-hosting server** to
  preview the loopback URL, bundle directory, port, Docker requirement, and
  networking responsibility before any write. It creates/starts the Compose
  bundle, captures first boot, waits until the server answers `/v1/health`,
  and activates the owner-only local connection.
- Wizard on another machine: pick **A team server** and enter its reachable URL
  first. Company sign-in (OIDC), when configured, opens the workbench with a
  one-time code so you approve your own machine. Otherwise provide a pasted
  API token or token-file path. The guided host screen teaches the handoff without configuring
  VPN/tailnet, LAN, port-forwarding, or TLS for you.
- Manual/operator path: `yoke self-host init --start` writes and starts the same Compose
  bundle through the private host secret handoff. Restart with
  `yoke self-host init --dir PATH --protect-existing --start`; [`docs/self-host.md`](https://github.com/upyoke/yoke/blob/main/docs/self-host.md)
  remains the full reference.
- The server serves the workbench at its own URL. People sign in with company
  sign-in (OIDC) and work with full read and write as their own actor; see
  [Browser Sign-In](https://github.com/upyoke/yoke/blob/main/docs/self-host-browser-sign-in.md)
- Members and Billing tabs do not apply (Cloud-only platform features)

`yoke self-host init` warns when `YOKE_API_PUBLISH` in the bundle's `.env`
publishes beyond loopback. Docker bypasses ufw/firewalld for published ports;
bind to `127.0.0.1` behind a TLS reverse proxy, or restrict access upstream.
The warning never blocks setup or startup. Declare the TLS proxy's transport
IPs/CIDRs in `.env` as `YOKE_API_TRUSTED_PROXIES`, then restart with
`yoke self-host init --dir PATH --protect-existing --start`. Preserve Host and
forward `X-Forwarded-Proto` and `X-Forwarded-For`; undeclared peers are ignored.

## Source available

Yoke is Fair Source (FSL-1.1-ALv2). Use, modify, and self-host; the license
converts to Apache 2.0 after its fixed window. Public source:
[github.com/upyoke/yoke](https://github.com/upyoke/yoke).

The wizard's **Edit Yoke source** row accepts an existing checkout or any
public fork. That checkout powers the local CLI and harness, and powers the
in-process engine in Local mode. If the same machine is also the guided
self-host, Yoke uses its existing checkout build/start path for the server
image. Existing remote self-hosted and Cloud servers are not redeployed by
this choice; they continue running their deployed build.

## Switching later

Universes are portable between modes via export/import. The client reconnects;
you do not re-author strategy or backlog from scratch.

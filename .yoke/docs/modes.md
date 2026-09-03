# Modes

One installer. After install, choose where the Yoke core and its database live.

## Local

Private on your machine. No signup. One human, as many agents as you want.

- Wizard: pick **This machine**, or run `yoke init --local`
- Data under `~/.yoke/`
- Open the workbench with `yoke ui up` (detached; `yoke ui` reports it, `yoke ui down` stops it)
- Members and Billing tabs do not apply (Cloud-only platform features)

Portable: `yoke universe export` dumps the universe; import it later into
self-hosted or another local machine.

## Yoke Cloud

Hosted core at upyoke.com. Collaborate from the web dashboard.

- Wizard: pick **upyoke.com**
- Sign-in, beta-code redemption, org founding, and machine approval happen in
  the connect step
- Private beta: seats and tenant attached to the code; bring your own workers
  and model credentials
- Members and Billing are platform-managed sections in the workbench

## Self-hosted

Run Yoke core and Postgres on your own server.

- Wizard on the host: pick **Set this machine up as a self-hosting server** to
  preview the loopback URL, bundle directory, port, Docker requirement, and
  networking responsibility before any write. It creates/starts the Compose
  bundle, captures first boot, waits until the server answers `/v1/health`,
  and activates the owner-only local connection.
- Wizard on another machine: pick **A team server** and enter its reachable URL
  plus a token. The guided host screen teaches the handoff without configuring
  VPN/tailnet, LAN, port-forwarding, or TLS for you.
- Manual/operator path: `yoke self-host init` writes the same published Compose
  bundle; `docs/self-host.md` remains the full reference.
- Same product surfaces as Cloud for Yoke-owned tabs; platform Member/Billing
  sections depend on how you host the shell

## Source available

Yoke is Fair Source (FSL-1.1-ALv2). Use, modify, and self-host; the license
converts to Apache 2.0 after its fixed window. Public source:
[github.com/upyoke/yoke](https://github.com/upyoke/yoke).

## Switching later

Universes are portable between modes via export/import. The client reconnects;
you do not re-author strategy or backlog from scratch.

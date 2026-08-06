# Modes

One installer. After install, choose where the Yoke core and its database live.

## Local

Private on your machine. No signup. One human, as many agents as you want.

- Wizard: pick **This machine**, or run `yoke init --local`
- Data under `~/.yoke/`
- Open the workbench with `yoke ui`
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

- `yoke self-host init` writes the published compose bundle
- Point the client at your server URL + token during onboard
- Same product surfaces as Cloud for Yoke-owned tabs; platform Member/Billing
  sections depend on how you host the shell

## Source available

Yoke is Fair Source (FSL-1.1-ALv2). Use, modify, and self-host; the license
converts to Apache 2.0 after its fixed window. Public source:
[github.com/upyoke/yoke](https://github.com/upyoke/yoke).

## Switching later

Universes are portable between modes via export/import. The client reconnects;
you do not re-author strategy or backlog from scratch.

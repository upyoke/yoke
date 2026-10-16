# Events

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Operations](index.md) > Events
<!-- /yoke:breadcrumbs -->

Read workbench telemetry, collector admission and durable visitor attribution.

## Events

The workbench collects usage analytics from first load in every mode — local,
self-hosted, and hosted — with no consent prompt, banner, or toggle; nothing it
collects is personal data, and a local or self-hosted workbench collects into
its own universe. The first load captures the visitor's attribution cookie, and
that load and each client navigation that changes the path emit `PageViewed`
with `event_type=page_view`. Query-only, fragment-only, and state-only
navigation (filters, `?selection=all` rewrites) emits no view. The workbench
names each screen in the browser title before the URL changes, most specific
part first (`PREFIX-12 · Items · Yoke`, `Runs · Deployments · Yoke`), so each
view's `page_title` tells screens apart; a machine-approval code never enters
the title. The installed
Structured Events Pack removes `?token=`, `?user_code=`, other sensitive query
keys, userinfo, and fragments from `page_url` and referrer, and stores
`/machine-approval/<code>` as `/machine-approval/redacted` in `page_url`,
`page_path`, and referrer, in the browser and again in the collector. Only one page-view
tracker runs per document, so a host page that tracks its own views and mounts
the workbench records each navigation once.

The engine exposes anonymous `GET /api/events/config`, `POST /api/events`, and
`GET`/`POST /api/events/attribution`. The collector accepts only frontend
analytics, requires an exact match between browser Origin and the serving
scheme/host/port, checks `X-Events-Key` against its publishable key, and shares
its rate budget through Postgres. Remote serving requires HTTPS. For self-host,
set `YOKE_API_TRUSTED_PROXIES` in the bundle `.env` to the TLS proxy IPs/CIDRs,
preserve Host, and forward scheme/client headers; restart with
`yoke self-host init --dir PATH --protect-existing --start`.
Backend and operational writes retain their
authenticated boundary.

Each workbench sends to its own universe's collector. A local or self-hosted
workbench uses the serving universe's `/api/events`. A hosted shell serves
several universes from one origin, so it mounts the workbench with
`eventsEndpoint` set to the organization's own collector route
(`/api/orgs/<slug>/api/events`) and forwards that route, with the viewer's
session, to the tenant engine. A hosted mount without `eventsEndpoint` sends
nothing and warns `collector_endpoint_unconfigured`; it never falls back to a
shared collector.

Configuration returns only a publishable digest. The private cookie signing key
belongs to the organization in `organizations.events_signing_key`. Signed,
HttpOnly attribution cookies use tenant-specific names; HTTPS uses `__Host-`
cookies and Secure, while the loopback HTTP door uses port-specific HttpOnly
cookies. The attribution site domain is the serving host's registrable domain
on the Public Suffix List (app.upyoke.com counts upyoke.com as internal; an IP
or localhost is its own site), and sign-in provider returns such as
accounts.google.com never become a touch. `frontend_event_rate_limits` stores disposable request counts (60
requests per client/organization per minute), independently of event retention.
Collector event times require qualified RFC3339 with at most six fractional
digits and normalize to fixed-six UTC strings before native storage. Signed
cookie and handoff instants use that same representation; old numeric-expiry
payloads are discarded and attribution is captured again. Rate-window starts
and redemption expiries are native PostgreSQL instants; rate windows preserve
their 60-second UTC epoch alignment.
The server stamps organization, environment (`YOKE_ENVIRONMENT`), and the
viewer's verified actor: a bearer token, the self-hosted `yoke_web_session`
cookie, or, on the Local view, the per-run token that admits the local
operator. A page view without one stays anonymous and carries only the
browser's `visitor_id`. The emitter's `service` and `project` are stored as
sent (`web` and `yoke` for the workbench); browser-supplied identity and
project/work-item references cannot choose their durable owners, so the row
indexes as global.
Accepted batches deduplicate on event UUIDs through the existing event sink.
Collector envelopes use INFO severity and are acknowledged only after sink
completion; failures return `collector_unavailable`, never false success.

Refusals include `origin_not_allowed`, `publishable_key_invalid`, `rate_limited`
(with Retry-After), `envelope_invalid`, and size limits. Each gives a recovery
step. The Pack retries failed batches with their original event IDs. Telemetry
remains disposable: using Yoke never depends on its successful delivery.

Each refusal also records one `FrontendCollectorRefused` backend event (reason,
status, route, truncated Origin, serving host; no body, cookie, key or client
address), at most once per reason, status and route per minute, so floods stay
bounded. The rows carry no project, so read them with `yoke db read`:
`yoke db read "SELECT created_at, event_outcome, envelope::jsonb -> 'context' -> 'detail' AS detail FROM events WHERE event_name = 'FrontendCollectorRefused' ORDER BY created_at DESC LIMIT 20"`.
Accepted frontend events take `created_at` from the collector's receipt time;
the envelope keeps the client `event_time` with `received_at` and
`client_time_offset_seconds`, and rows more than 300 seconds off carry
`anomaly_flags = 'client_time_skew'`.

Source maintainers install the project-owned Structured Events Pack, then run
`yoke dev run -- python3 -m yoke_core.tools.build_frontend_events` from the lane.
This derives browser JavaScript and package-relative Python helpers from the
installed `events/` files; it does not change the Pack or its baseline receipt.
Generated helpers and rule data ship in the engine wheel. Rebuild them after
an accepted Pack update; `--check` reports stale outputs. Node >=22.13 is needed
only to build, while installed engines need no Node runtime for collection.

Workbench **Events** is the audit stream: lifecycle, claims, deploy, doctor
findings, function calls. Filter by name and time when debugging "what
happened."

Account acquisition is durable state: a signed-in flow creating an actor stores
the verified attribution cookie's visitor identity, first touch, and last touch
in `actors.attribution`. Later sign-ins preserve that acquisition snapshot and
add a [visitor link](#visitor-links) for the browser they come from. A
flow without an attribution cookie creates an actor with no attribution. The event ledger is never
used to reconstruct this account fact and may be pruned independently.

**Search loaded events** searches the entries already loaded and offers
observed names as suggestions. Advanced filters keep the precise server-side
event name, source, severity and time constraints. The loaded scope remains
explicit; text search does not promise matches outside it.

### Visitor links

`actor_visitor_links` is the durable list of browsers each actor has signed in
from: one row per `visitor_id`, owned by its `actor_id`. Every web sign-in
(company OIDC or `yoke ui up` browser admission) links the browser's verified
visitor id to the signed-in actor, so an actor gains one link per browser or
device. A visitor id already linked to another actor is never re-linked: the
sign-in proceeds, the server logs `visitor_linked_to_other_actor`, and the row
records `refused_actor_id`/`refused_at`. `actors.attribution` remains the
signup snapshot. Sign-out (Profile → Sign out, `POST /v1/auth/sign-out`)
revokes the web session and clears the attribution cookie, so the next person
on a shared browser starts under a fresh visitor id.

Events are never rewritten. Tie a browser's anonymous page views to their
actor at query time:

```sql
SELECT e.* FROM events e
JOIN actor_visitor_links l ON l.visitor_id = (e.envelope::jsonb ->> 'visitor_id')
WHERE e.source_type = 'frontend' AND l.actor_id = <actor id>;
```

## Related

- [Event model](model/events.md)
- [Doctor](doctor.md)
- [Performance diagnostics](performance-diagnostics.md)

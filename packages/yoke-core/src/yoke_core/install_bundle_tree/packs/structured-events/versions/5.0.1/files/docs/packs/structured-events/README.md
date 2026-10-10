# Structured Events Pack 4.0.0

Python and TypeScript envelopes, first/last-touch attribution,
a signed server-set visitor cookie, SPA views, retrying batches, and an anonymous
collector contract. See [integration](../../../events/README.md).

Install the whole bundle. Set project identity, own site domain, collector
publishable key, exact origin allowlist and private server signing secret in
project-owned settings. No provider secrets belong in browser code or Pack source.
The durable account/signup attribution owner, storage adapter,
shared rate limiter and retention policy belong to the consuming project.

Run `python3 -m pytest events` and
`node --experimental-strip-types --test events/test_browser.mjs` (Node >=22.6).
Events, page views and attribution capture run from first load with no consent
state; collect only non-personal data. Page tracking is document-wide: a host
page and an embedded app that each bundle this Pack start one tracker between
them.

Verified cookie reads and signed, one-time cross-origin sign-in hand-offs are
server-only APIs; supply durable atomic nonce storage. See the integration
guide for routes, destination binding and named refusals.

The timestamp resources are canonical shared contracts shipped with the Pack.
Event and attribution clocks and signed expiry payloads use six-digit UTC
RFC3339 strings; Python native storage callbacks receive aware UTC datetime.
Drop old signed cookies and restart old handoffs during adoption. Qualified
new input preserves microseconds; malformed or offset-free clocks refuse
before storage. See the installed events guide for exact callback contracts.

UTC conversion outside years 1 through 9999 refuses with `invalid_instant`; valid boundary instants retain all six fractional digits.

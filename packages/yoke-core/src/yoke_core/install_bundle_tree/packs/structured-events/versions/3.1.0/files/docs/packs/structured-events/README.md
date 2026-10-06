# Structured Events Pack 3.1.0

Python and TypeScript envelopes, consent-gated first/last-touch attribution,
a signed server-set visitor cookie, SPA views, retrying batches, and an anonymous
collector contract. See [integration](../../../events/README.md).

Install the whole bundle. Set project identity, own site domain, collector
publishable key, exact origin allowlist and private server signing secret in
project-owned settings. No provider secrets belong in browser code or Pack source.
The consent UI, durable account/signup attribution owner, storage adapter,
shared rate limiter and retention policy belong to the consuming project.

Run `python3 -m pytest events` and
`node --experimental-strip-types --test events/test_browser.mjs` (Node >=22.6).
Version 3 replaces the old storage shape; there is no old-cookie read path.
3.1.0 makes page tracking document-wide: a host page and an embedded app that
each bundle this Pack start one tracker between them. Old immutable Pack
releases remain available as version history.

Verified cookie reads and signed, one-time cross-origin sign-in hand-offs are
server-only APIs; supply durable atomic nonce storage. See the integration
guide for routes, destination binding, consent timestamps and named refusals.

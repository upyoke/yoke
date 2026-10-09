# Structured Events Pack 4.1.0

Python and TypeScript envelopes, first/last-touch attribution,
a signed server-set visitor cookie, SPA views, retrying batches, and an anonymous
collector contract. See [integration](../../../events/README.md).

Install the whole bundle. Set project identity, own registrable site domain, collector
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

Referrers from the own site domain or a sign-in provider listed in
excluded_referrer_domains are internal and never become a touch.

Verified cookie reads and signed, one-time cross-origin sign-in hand-offs are
server-only APIs; supply durable atomic nonce storage. See the integration
guide for routes, destination binding and named refusals.

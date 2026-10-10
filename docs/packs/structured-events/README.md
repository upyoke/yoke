# Structured Events Pack 4.3.0

Python and TypeScript envelopes, first/last-touch attribution,
a signed server-set visitor cookie, SPA views, retrying batches, and an anonymous
collector contract. See [integration](../../../events/README.md).

Install the whole bundle. Set project identity, own registrable site domain, collector
publishable key, exact origin allowlist and private server signing secret in
project-owned settings. No provider secrets belong in browser code or Pack source.
The durable account/signup attribution owner, storage adapter,
shared rate limiter and retention policy belong to the consuming project.

The collector classifies browser, OS and device type from request headers; add
`ua-parser[regex]>=1.0` to Python dependencies and `bowser` to package.json.
Run `python3 -m pytest events` and
`node --experimental-strip-types --test events/test_browser.mjs` (Node >=22.6).
Events, page views and attribution capture run from first load with no consent
state; collect only non-personal data. A page view follows the path: query-only
and fragment-only navigation emits no view. Page tracking is document-wide: a
host page and an embedded app that each bundle this Pack start one tracker
between them.

Stored URLs drop sensitive query keys (including the device-login user_code)
and mask the segment after machine-approval as /machine-approval/redacted in
page_url, page_path and referrer.

Referrers from the own site domain or a sign-in provider listed in
excluded_referrer_domains are internal and never become a touch.

The collector stamps each accepted event with its own receipt time; store
received_at as the row time and keep the client event_time as a claim. An
optional recordRefusal sink receives each refusal kind at most once per minute
as disposable diagnostics.

Verified cookie reads and signed, one-time cross-origin sign-in hand-offs are
server-only APIs; supply durable atomic nonce storage. See the integration
guide for routes, destination binding and named refusals.

# Structured Events Pack 5.2.0

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
state. Events carry visitor identity and browser language, time zone, screen
and viewport; collector-added client IP is personal data. Obtain permission
before public launch. A page view follows the path: query-only
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

The timestamp resources are canonical shared contracts shipped with the Pack.
Event and attribution clocks and signed expiry payloads use six-digit UTC
RFC3339 strings; Python native storage callbacks receive aware UTC datetime.
Drop old signed cookies and restart old handoffs during adoption. Qualified
new input preserves microseconds; malformed or offset-free clocks refuse
before storage. See the installed events guide for exact callback contracts.

UTC conversion outside years 1 through 9999 refuses with `invalid_instant`; valid boundary instants retain all six fractional digits.


Optional device facts use standard browser APIs, with no prompts or active
fingerprinting. Fields are absent when an API is unavailable or its value is
unusable; a failed lookup never drops the event:

| Field | Source |
| --- | --- |
| `os_version` | Client Hints `platformVersion`; collector parses iOS/iPadOS User-Agent and overrides it; no frozen macOS Safari version |
| `device_model` | Client Hints `model` |
| `cpu_architecture` | Client Hints `architecture` |
| `cpu_bitness` | Client Hints `bitness` |
| `cpu_cores` | `navigator.hardwareConcurrency` |
| `device_memory_gb` | `navigator.deviceMemory` (browser rounded and capped) |
| `pixel_ratio` | `window.devicePixelRatio` |
| `color_depth` | `screen.colorDepth` |
| `touch_points` | `navigator.maxTouchPoints` |
| `gpu_renderer` | WebGL `UNMASKED_RENDERER_WEBGL`, including generic values |
| `connection_type` | `navigator.connection.effectiveType` |
| `connection_downlink_mbps` | `navigator.connection.downlink` |

Client Hints resolve once per page, never delaying a view; flush fills resolved
hints into queued events. WebGL is read once from a throwaway context without
rendering or reading pixels. No canvas image, audio or font probing, hashing or
combined device identifier is collected. These are disposable telemetry; no
operational code reads them. The collector drops invalid facts without rejecting
the event: nonempty strings up to 128 characters; CPU cores integer 1..1024;
memory >0..1024 GB; pixel ratio >0..16; touch points integer 0..256; color depth
integer 1..64; downlink 0..100000 Mbps. Other envelope fields still pass through.

# Browser action budgets and failure evidence

Arm the monotonic timer and required creating-state captures before the
mutating action. Submit it once, record its start and next-screen observation,
and keep those measurements separate from network-response time.

```text
yoke qa browser step --base-url https://example.test --step-json '{"action":"click","target":"#submit","timeout_ms":120000}'
yoke qa browser status
```

A finite positive numeric `timeout_ms` gives that request the greater of
30 seconds or the declared action seconds plus 15 seconds of response
headroom. Ordinary calls keep the 30-second transport default; missing,
nonpositive, boolean and nonfinite budgets do not extend it. The action still
owns its own wait budget. Transport headroom does not measure product speed.

`browser_daemon_response_timeout` means the client stopped receiving an
answer. The action may have completed; it was not undone. Inspect the
existing page and retained evidence before recovery. Never replay a submit
blindly or create another real transaction to replace missing evidence.

`browser_daemon_http_error` includes the bounded, credential-scrubbed daemon
payload when available. Diagnose the retained reason; HTTP 400 alone does
not prove navigation, a missing page or any other specific cause. Check
`yoke qa browser status` for daemon health.

A native navigation can replace the document during a media-preference
read. The daemon allows that read to settle against the new document while
keeping the same owned page, viewport and requested theme; it never repeats
the action. Persistent observation failures remain named refusals.

A missing creating-state capture or exact submit-to-next-screen measurement
stays unknown when retained evidence cannot establish it. Keep the original
assertions and failed capture evidence. A new real acceptance transaction
needs explicit operator authorization; an eventual next screen is not proof
of the missing intermediate state or elapsed time.

See [Browser scenarios](../verification/browser-scenarios.md) for actions and capture framing.

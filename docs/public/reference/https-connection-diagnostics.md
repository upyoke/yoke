# HTTPS connection diagnostics

Yoke keeps TLS certificate verification enabled for local, self-hosted and
hosted HTTPS endpoints. Both function-relay calls and bounded JSON clients
report `certificate_validation_failed` with the verifier's known reason.
Diagnostics redact request credentials, escape terminal controls and bound
certificate reason text.

A direct or urllib-wrapped certificate validation failure stops after one
attempt: the same invalid certificate cannot succeed unchanged. When the
verifier identifies expiration, renew the serving certificate and check the
client clock. For a hostname mismatch, correct the endpoint hostname or
serve a certificate covering it. For an untrusted chain, repair the server
chain or configure the client's trusted CA store with the intended authority.
An unspecified validation failure does not establish expiration: ask the
endpoint operator to inspect the certificate and chain, and check the clock,
hostname and trusted CA store. Retain TLS verification during repair.

Confirmed OS permission denials also stop promptly and direct the caller to
network access policy. Harness permission guidance is conditional on its
sandbox causing that denial. Launcher identity alone does not diagnose a
sandbox failure. Unknown DNS or reachability failures retain bounded retries
and describe their cause as unknown; check reachability and DNS. A loopback
connection refusal still directs the caller to start the server or select
another authority. Transient resets and server unavailability retain their
retry budgets, deadlines and response bounds. Every relay attempt uses the
same request body and request id for replay safety.

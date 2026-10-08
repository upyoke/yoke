# Domain instants and UTC wire values

`yoke_contracts.timestamps` owns the Python instant boundary. Database writers
use `utc_now()` or `parse_instant(value)` to bind an aware `datetime`. Owned
wire values and files use `format_instant(value)` or `iso8601_now()` to produce
`YYYY-MM-DDTHH:MM:SS.ffffffZ`. Optional unknown values are null where the owner
permits absence. Fractional zero padding does not recover measurement precision.

Supplied inputs require a valid calendar and an explicit UTC offset. Naive
datetimes, date-only values, unknown `-00:00` offsets and precision beyond
microseconds refuse as `invalid_instant`; supply a qualified instant instead.
Offset-qualified inputs normalize to the same UTC instant without dropping
microseconds. No parser guesses a local timezone or repairs malformed history.

`temporal_wire(value)` converts native datetimes within result dictionaries and
sequences, preserving nulls. It leaves strings untouched: timestamp-shaped
prose, identifiers and immutable historical documents retain their meaning and
bytes. Each mutable document owner validates its declared timestamp fields at
ingress. Function response serialization and the idempotency result ledger
share this conversion, so HTTP, CLI and local response envelopes agree.

Calendar days retain an explicit bucket timezone. Durations retain their units;
elapsed process deadlines use a monotonic clock. JWT/OIDC NumericDate, AWS,
HTTP and native third-party formats remain external protocol encodings, with
conversion at the owning adapter. Internal signing does not turn an owned
timestamp format into an external protocol. Preserve historical immutable
receipt bytes; new generations use canonical UTC. Historical repairs and active
credential or operation cutovers require evidence from their existing owners.

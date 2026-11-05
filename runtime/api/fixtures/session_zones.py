"""Session zones shared by instant tests; calendar boundaries need both signs."""

# Both offsets include minutes. Ordinary storage tests use the positive zone;
# UTC calendar buckets and the registry roundtrip proof use both directions.
SESSION_ZONES = ("America/St_Johns", "Asia/Kathmandu")

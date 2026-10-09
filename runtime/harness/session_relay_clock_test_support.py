"""Native clocks for relay cadence fixtures; numeric inputs denote elapsed seconds."""

from datetime import timedelta

from yoke_contracts.timestamps import parse_instant

_ORIGIN = parse_instant("1970-01-01T00:00:00.000000Z")


def at(seconds):
    return _ORIGIN + timedelta(seconds=seconds)

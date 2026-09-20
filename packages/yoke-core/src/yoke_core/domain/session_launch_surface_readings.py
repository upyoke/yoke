"""Headroom readings for the surfaces a launch did not ask about.

Placement ranks machines *within* one surface, because the surface is an input
the caller has already decided by the time a launch is composed. That leaves
the surface choice itself unmeasured at the moment it is made: a composer names
a surface, the launch succeeds on a loaded one, and the idle capacity sitting on
another surface of the same fleet is visible only in a report read nowhere near
the decision.

These readings put that number in the launch's own output, so the choice is
informed by the act rather than by remembering to look first.

They are meter readings and not an eligibility verdict. A surface can publish
all the headroom in the world and still have no relay answering on it, and
surfaces are not freely substitutable anyway -- they differ in capability, not
just in capacity. What the readings support is noticing that somewhere roomier
exists; whether a launch may go there is the placement result's own answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SurfaceHeadroomReading:
    """The binding headroom one machine publishes for one surface."""

    machine_id: str
    surface: str
    headroom_percent: float
    headroom_window: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def unrequested_surface_readings(
    headroom: dict[tuple[str, str], tuple[float, str]],
    *,
    requested_surface: str,
) -> tuple[SurfaceHeadroomReading, ...]:
    """Readings for every surface other than the requested one, roomiest first.

    ``headroom`` is the per-``(machine, surface)`` map placement already reads
    to rank machines, so naming the alternatives costs no additional query.
    Roomiest first because the only question these rows answer is whether there
    was somewhere with more room than the surface the caller named.
    """
    readings = [
        SurfaceHeadroomReading(
            machine_id=machine_id,
            surface=surface,
            headroom_percent=percent,
            headroom_window=window,
        )
        for (machine_id, surface), (percent, window) in headroom.items()
        if surface != requested_surface
    ]
    readings.sort(
        key=lambda reading: (
            -reading.headroom_percent,
            reading.machine_id,
            reading.surface,
        )
    )
    return tuple(readings)


__all__ = ["SurfaceHeadroomReading", "unrequested_surface_readings"]

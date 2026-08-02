"""The three places a Yoke control plane can live.

One shared engine, three deployment destinations: the machine's own
embedded local universe, a self-hosted team server, or the hosted
platform. Onboarding picks one; anything that reasons about where code is
executing relative to the control plane names the same three values, so
they live here where every package can import them.
"""

from __future__ import annotations

DESTINATION_LOCAL = "local"
DESTINATION_SERVER = "server"
DESTINATION_HOSTED = "hosted"

#: Every destination, in the order the onboarding picker offers them.
DESTINATIONS = (DESTINATION_LOCAL, DESTINATION_SERVER, DESTINATION_HOSTED)

__all__ = [
    "DESTINATIONS",
    "DESTINATION_HOSTED",
    "DESTINATION_LOCAL",
    "DESTINATION_SERVER",
]

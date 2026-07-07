"""Compatibility shim — ``now_sql`` moved to the shipped ``yoke_contracts.time_sql``
tier so the board render (and any client-tier caller) can build its SQL fragments
without ``yoke_core``. Transitional re-export for existing importers.
"""

from yoke_contracts import time_sql as _moved

globals().update({k: v for k, v in vars(_moved).items() if not k.startswith("__")})

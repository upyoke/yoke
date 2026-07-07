"""Compatibility re-export — machine-config runtime accessors moved to
yoke_contracts.machine_config.runtime (next to the schema they read)."""
from yoke_contracts.machine_config import runtime as _moved
globals().update({k: v for k, v in vars(_moved).items() if not k.startswith("__")})

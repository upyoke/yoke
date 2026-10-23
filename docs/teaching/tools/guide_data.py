"""Source inventories and authored research consumed by the unified guide."""
from dataclasses import dataclass
from collections.abc import Callable
from model import Model


@dataclass
class GuideData:
    m: Model
    live: dict
    docs: dict
    area_of: Callable

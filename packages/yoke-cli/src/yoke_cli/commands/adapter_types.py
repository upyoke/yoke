"""Types shared by tool-shaped CLI adapters."""

from collections.abc import Callable

AdapterFn = Callable[[list[str]], int]

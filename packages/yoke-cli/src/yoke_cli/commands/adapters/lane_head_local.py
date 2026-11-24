"""Load the engine that observes this command's machine-local lane."""

from importlib import import_module


def lane_head_engine():
    return import_module("yoke_core.domain.lane_head_client")

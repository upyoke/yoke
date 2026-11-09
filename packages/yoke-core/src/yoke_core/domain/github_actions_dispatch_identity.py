"""Stable tag identity for deployment workflow dispatch."""

DISPATCH_TAG_PREFIX = "yoke-deploy/"


def dispatch_tag_name(run_id: str) -> str:
    """The tag a deployment run's stages are dispatched at."""
    return f"{DISPATCH_TAG_PREFIX}{run_id}"

"""Yoke engines package.

Each engine is a ``__main__.py``-style module that can be invoked via
``python3 -m yoke_core.engines.<name>``.  Engines replace shell scripts
that previously orchestrated SQLite, git, JSON, and text pipelines through
repeated subprocess fan-out.
"""

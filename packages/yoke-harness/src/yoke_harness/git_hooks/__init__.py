"""Product-safe git hook bodies for the installable ``yoke`` CLI."""

from yoke_harness.git_hooks.pre_commit import run as run_pre_commit

__all__ = ["run_pre_commit"]

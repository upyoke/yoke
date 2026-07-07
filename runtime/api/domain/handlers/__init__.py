"""Namespace package for Yoke function handlers.

Handler modules live in this package and call ``register(...)`` from
``yoke_core.domain.yoke_function_registry`` at import time. The
canonical entry point is
:func:`yoke_core.domain.handlers.__init_register__.register_all_handlers`
which the FastAPI lifespan calls once on startup.

Empty namespace at task 1 close: handlers land in tasks 3-7.
"""

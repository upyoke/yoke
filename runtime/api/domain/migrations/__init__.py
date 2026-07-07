"""Governed migration modules for the Yoke primary model.

Each module in this directory exports a callable ``apply(conn)`` that the
governed migration runner imports and executes inside a transaction it
owns. The directory path is declared on the migration model capability
under ``runner.config.modules_dir``.
"""

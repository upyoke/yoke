"""Yoke board render — the project-universal status-board presentation tier.

The board is a per-project artifact that must render for *any* managed project,
including external projects with no Yoke checkout and no ``yoke_core``. The
render is pure presentation over an already-fetched data payload (see
``yoke_core``'s ``board.data.get`` record/replay seam), so it lives in the
already-shipped ``yoke_contracts`` tier — importing only ``yoke_contracts``
itself + stdlib, never ``yoke_core`` or psycopg. Callers import the submodules
directly (e.g. ``from yoke_contracts.board.art_render import render_header``).
"""

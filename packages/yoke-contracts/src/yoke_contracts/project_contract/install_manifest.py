"""Where a project install records the files it placed.

``.yoke/install-manifest.json`` records what *this machine's* install placed.
It is gitignored and absent from a fresh clone or a CI runner, so nothing
that classifies a committed file may consult it.
"""

from __future__ import annotations


INSTALL_MANIFEST_REL = ".yoke/install-manifest.json"


__all__ = [
    "INSTALL_MANIFEST_REL",
]

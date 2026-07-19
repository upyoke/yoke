"""Wire constants shared by Pack catalog, API, CLI, and project receipts."""

from __future__ import annotations


PACK_DESCRIPTOR_SCHEMA = 1
PACK_BUNDLE_SCHEMA = 1
PACK_RECEIPT_SCHEMA = 1
PACKS_SOURCE = "packs"
PACK_RECEIPT_REL = ".yoke/packs.json"


__all__ = [
    "PACK_BUNDLE_SCHEMA",
    "PACK_DESCRIPTOR_SCHEMA",
    "PACK_RECEIPT_REL",
    "PACK_RECEIPT_SCHEMA",
    "PACKS_SOURCE",
]

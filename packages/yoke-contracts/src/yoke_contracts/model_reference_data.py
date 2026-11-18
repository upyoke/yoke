"""Shipped model catalog: the defaults every install follows.

``model_reference_data.json`` holds the records in the shape
`yoke models get --json` returns them. Each boot appends them as a ``shipped``
catalog revision while the universe follows shipped defaults
(:mod:`yoke_core.domain.model_reference_shipped`). Refresh them in a Dash
together with ``level_defaults.py``; the release carries them to every install.

Records describe models only; the execution levels decide which model a worker
launches. Unknown leaves stay null; an inferred rate is filled only with its
``estimated_fields`` label and a stated basis. API dollars are not
subscription percentages: a plan's own metered weighting rides on the
subscription rule as a consumption weight and is never summed with money.
"""

from __future__ import annotations

import json
from importlib import resources

from yoke_contracts.model_reference import validate_model_record
from yoke_contracts.model_reference_records import ModelRecord

DATA_RESOURCE = "model_reference_data.json"


def _load_records() -> tuple[ModelRecord, ...]:
    text = resources.files("yoke_contracts").joinpath(DATA_RESOURCE).read_text(
        encoding="utf-8"
    )
    return tuple(validate_model_record(payload) for payload in json.loads(text))


MODEL_RECORDS: tuple[ModelRecord, ...] = _load_records()

__all__ = ["DATA_RESOURCE", "MODEL_RECORDS"]

# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from itertools import permutations

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)

from runtime.api.domain.standalone_item_merge_qa_test_support import MERGING_SHA, _item

from yoke_core.domain.item_detail_qa import qa_rows

from yoke_core.domain.standalone_item_merge_qa import preflight


def _proof(conn, item_id, tmp_path):
    item = _item(None)
    item["qa_requirements"] = qa_rows(conn, item_id, include_proof=True)
    return item, preflight(
        item, public_ref="example", repo_root=tmp_path, branch="lane"
    )

"""Handler tests for qa.requirement.auto_create_for_item.

Companion to :mod:`runtime.api.test_api_qa_function`. Carried in a
sibling module because the new test class plus its mocks would push the
parent file over the 350-line authored cap; the original spec named
this filename as a planned fallback for exactly this case.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import qa
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(target: TargetRef) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.auto_create_for_item",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
    )


class _RowCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row=None):
        self._row = row

    def execute(self, sql, params):
        return _RowCursor(self._row)

    def close(self):
        pass


class TestQaRequirementAutoCreateForItem(unittest.TestCase):
    def test_rejects_missing_target(self):
        outcome = qa.handle_qa_requirement_auto_create_for_item(
            _request(TargetRef(kind="global")),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_existing_requirement_returns_existing_outcome(self):
        with patch(
            "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
        ):
            with patch(
                "yoke_core.domain.qa_requirements_auto._existing_requirement",
                return_value=4242,
            ):
                outcome = qa.handle_qa_requirement_auto_create_for_item(
                    _request(TargetRef(kind="item", item_id=99)),
                )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["outcome"], "existing")
        self.assertEqual(outcome.result_payload["requirement_id"], 4242)
        self.assertEqual(outcome.result_payload["item_id"], 99)

    def test_missing_item_returns_not_found_error(self):
        with patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Conn(row=None),
        ):
            with patch(
                "yoke_core.domain.qa_requirements_auto._existing_requirement",
                return_value=None,
            ):
                outcome = qa.handle_qa_requirement_auto_create_for_item(
                    _request(TargetRef(kind="item", item_id=12345)),
                )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")

    def test_browser_testable_item_returns_noop(self):
        item_row = {
            "id": 7, "type": "issue",
            "browser_qa_metadata": '{"browser_testable": true}',
            "spec": "",
        }
        with patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Conn(row=item_row),
        ):
            with patch(
                "yoke_core.domain.qa_requirements_auto._existing_requirement",
                return_value=None,
            ):
                outcome = qa.handle_qa_requirement_auto_create_for_item(
                    _request(TargetRef(kind="item", item_id=7)),
                )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["outcome"],
                         "browser_testable_noop")
        self.assertIsNone(outcome.result_payload["requirement_id"])

    def test_non_issue_returns_not_applicable(self):
        item_row = {
            "id": 8, "type": "epic", "browser_qa_metadata": "",
            "spec": "",
        }
        with patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Conn(row=item_row),
        ):
            with patch(
                "yoke_core.domain.qa_requirements_auto._existing_requirement",
                return_value=None,
            ):
                outcome = qa.handle_qa_requirement_auto_create_for_item(
                    _request(TargetRef(kind="item", item_id=8)),
                )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["outcome"], "not_applicable")

    def test_creates_requirement_for_non_browser_issue(self):
        item_row = {
            "id": 21, "type": "issue", "browser_qa_metadata": "",
            "spec": "## Acceptance Criteria\n- [ ] AC-1: do the thing\n",
        }
        with patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Conn(row=item_row),
        ):
            with patch(
                "yoke_core.domain.qa_requirements_auto._existing_requirement",
                return_value=None,
            ):
                with patch(
                    "yoke_core.domain.qa_requirements_auto.auto_create_for_item",
                    return_value=777,
                ) as inner:
                    outcome = qa.handle_qa_requirement_auto_create_for_item(
                        _request(TargetRef(kind="item", item_id=21)),
                    )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["outcome"], "created")
        self.assertEqual(outcome.result_payload["requirement_id"], 777)
        inner.assert_called_once_with(21)


if __name__ == "__main__":
    unittest.main()

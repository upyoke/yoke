"""Shared fixture identity for QA plan execution tests."""

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"
TEST_EXECUTION_TARGET = {
    "environment": {"name": "development"},
    "endpoints": {"app_url": "", "api_url": ""},
}


__all__ = ["TEST_EXECUTION_TARGET", "TEST_ITEM_ID", "TEST_ITEM_REF"]

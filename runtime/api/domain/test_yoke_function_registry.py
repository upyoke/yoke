"""Tests for the Yoke function-call registry."""

from __future__ import annotations

import unittest

from pydantic import BaseModel

from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.yoke_function_registry import (
    RegistryDuplicateError,
    RegistryValidationError,
    list_entries,
    lookup,
    register,
    reset_registry_for_tests,
    schema_for,
)


class _ReqA(BaseModel):
    item_id: int


class _RespA(BaseModel):
    new_status: str


def _handler(_request):
    return HandlerOutcome(result_payload={"ok": True}, primary_success=True)


def _stable_kwargs(**overrides):
    base = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_module",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["FakeEvent"],
        "guardrails": [],
        "adapter_status": "live",
    }
    base.update(overrides)
    return base


class _RegistryTestBase(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()

    def tearDown(self) -> None:
        reset_registry_for_tests()


class TestRegistryEmpty(_RegistryTestBase):
    """AC-1.2: empty registry returns no entries until a handler registers."""

    def test_list_empty(self):
        self.assertEqual(list_entries(), [])

    def test_lookup_unknown_returns_none(self):
        self.assertIsNone(lookup("missing.family.op"))


class TestRegistryHappyPath(_RegistryTestBase):
    def test_register_and_lookup(self):
        register(
            "test.family.op",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(),
        )
        entry = lookup("test.family.op")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.function_id, "test.family.op")
        self.assertEqual(entry.target_kinds, ("item",))
        self.assertTrue(entry.ambient_session_required)

    def test_register_operator_callable_side_effect(self):
        register(
            "test.board.render",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(side_effects=["board_rewrite"]),
            ambient_session_required=False,
        )
        entry = lookup("test.board.render")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertFalse(entry.ambient_session_required)

    def test_schema_for_registered_id(self):
        register(
            "test.family.op",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(),
        )
        schema = schema_for("test.family.op")
        self.assertIn("properties", schema)
        self.assertIn("item_id", schema["properties"])

    def test_schema_for_missing_raises(self):
        with self.assertRaises(KeyError):
            schema_for("nope.family.op")


class TestRegistryValidation(_RegistryTestBase):
    """AC-1.4 + AC-1.5: duplicates and deprecation rules are enforced."""

    def test_duplicate_id_rejected(self):
        register(
            "test.family.op",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(),
        )
        with self.assertRaises(RegistryDuplicateError):
            register(
                "test.family.op",
                _handler,
                _ReqA,
                _RespA,
                **_stable_kwargs(),
            )

    def test_bad_id_shape_rejected(self):
        with self.assertRaises(RegistryValidationError):
            register(
                "badShape",
                _handler,
                _ReqA,
                _RespA,
                **_stable_kwargs(),
            )

    def test_deprecated_without_replacement_rejected(self):
        with self.assertRaises(RegistryValidationError):
            register(
                "test.family.op",
                _handler,
                _ReqA,
                _RespA,
                **_stable_kwargs(stability="deprecated"),
            )

    def test_deprecated_with_replacement_ok(self):
        entry = register(
            "test.family.op",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(stability="deprecated"),
            replacement_function_id="test.family.op_v2",
        )
        self.assertEqual(entry.replacement_function_id, "test.family.op_v2")

    def test_unknown_stability_rejected(self):
        with self.assertRaises(RegistryValidationError):
            register(
                "test.family.op",
                _handler,
                _ReqA,
                _RespA,
                **_stable_kwargs(stability="brand_new"),
            )

    def test_unknown_adapter_status_rejected(self):
        with self.assertRaises(RegistryValidationError):
            register(
                "test.family.op",
                _handler,
                _ReqA,
                _RespA,
                **_stable_kwargs(adapter_status="experimental"),
            )


class TestClaimRequiredKindEnumeration(_RegistryTestBase):
    """AC-1.15: registry accepts exactly the five canonical kinds."""

    def test_all_five_kinds_accepted(self):
        kinds = (None, "item", "epic", "self_only", "operator_override")
        for ix, kind in enumerate(kinds):
            register(
                f"test.kind.op_{ix}",
                _handler,
                _ReqA,
                _RespA,
                **_stable_kwargs(),
                claim_required_kind=kind,
            )
        ids = {e.function_id for e in list_entries()}
        self.assertEqual(len(ids), 5)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(RegistryValidationError):
            register(
                "test.family.op",
                _handler,
                _ReqA,
                _RespA,
                **_stable_kwargs(),
                claim_required_kind="not_a_kind",
            )


class TestFunctionIdShape(_RegistryTestBase):
    """AC-28: ids match ``<family>.<subfamily>.<operation>``."""

    def test_valid_three_segment_id(self):
        entry = register(
            "claims.work.acquire",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(),
        )
        self.assertEqual(entry.function_id, "claims.work.acquire")


class TestVersioningMetadata(_RegistryTestBase):
    """AC-30: registry preserves stability + replacement + removal_target_version."""

    def test_versioning_metadata_preserved(self):
        entry = register(
            "test.family.op",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(stability="deprecated"),
            replacement_function_id="test.family.op_v2",
            removal_target_version="v2",
        )
        self.assertEqual(entry.stability, "deprecated")
        self.assertEqual(entry.replacement_function_id, "test.family.op_v2")
        self.assertEqual(entry.removal_target_version, "v2")


if __name__ == "__main__":
    unittest.main()

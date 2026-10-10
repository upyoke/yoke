"""Tests for the Yoke function-call registry."""

from __future__ import annotations

import re
import unittest
from collections import Counter
from pathlib import Path

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
    """Empty registry returns no entries until a handler registers."""

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
        self.assertIn("public_ref", schema["properties"])

    def test_schema_for_missing_raises(self):
        with self.assertRaises(KeyError):
            schema_for("nope.family.op")


class TestRegistryValidation(_RegistryTestBase):
    """Duplicates and deprecation rules are enforced."""

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

    def test_internal_adapter_status_is_accepted(self):
        entry = register(
            "test.family.op",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(adapter_status="internal"),
        )
        self.assertEqual(entry.adapter_status, "internal")


class TestClaimRequiredKindEnumeration(_RegistryTestBase):
    """Registry accepts the canonical claim policies."""

    def test_all_claim_kinds_accepted(self):
        kinds = (None, "item", "epic", "qa_subject", "self_only", "steering")
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
        self.assertEqual(len(ids), len(kinds))

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
    """Ids match ``<family>.<subfamily>.<operation>``."""

    def test_valid_three_segment_id(self):
        entry = register(
            "claims.work.acquire",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(),
        )
        self.assertEqual(entry.function_id, "claims.work.acquire")


class TestServingFloorDeclaration(_RegistryTestBase):
    """Ids absent from the previous serving set must declare a floor."""

    def test_unserved_id_without_a_floor_is_rejected(self):
        from yoke_core.domain.yoke_function_registry import (
            require_floor_for_unserved_ids,
        )

        require_floor_for_unserved_ids()
        with self.assertRaises(RegistryValidationError) as ctx:
            register(
                "brand.new.op",
                _handler,
                _ReqA,
                _RespA,
                **_stable_kwargs(),
            )
        self.assertIn("minimum_serving_version", str(ctx.exception))

    def test_unserved_id_with_a_floor_is_recorded(self):
        from yoke_core.domain.yoke_function_registry import (
            require_floor_for_unserved_ids,
        )

        require_floor_for_unserved_ids()
        entry = register(
            "brand.new.op",
            _handler,
            _ReqA,
            _RespA,
            **_stable_kwargs(),
            minimum_serving_version="next-release",
        )
        self.assertEqual(entry.minimum_serving_version, "next-release")

    def test_engine_floors_match_the_client_readable_map(self):
        from yoke_contracts.function_serving_floors import (
            FUNCTION_MINIMUM_SERVING_VERSIONS,
        )
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers
        from yoke_core.domain.yoke_function_registry import (
            require_floor_for_unserved_ids,
        )

        require_floor_for_unserved_ids()
        register_all_handlers()
        engine = {
            e.function_id: e.minimum_serving_version
            for e in list_entries()
            if e.minimum_serving_version
        }
        self.assertEqual(dict(FUNCTION_MINIMUM_SERVING_VERSIONS), engine)


class TestFunctionDocumentation(_RegistryTestBase):
    def test_registered_catalog_is_complete_unique_and_reachable(self):
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers

        register_all_handlers()
        expected = {entry.function_id for entry in list_entries()}
        root = (
            Path(__file__).resolve().parents[3] / "docs/public/reference/db-reference"
        )
        families = (
            "claims items project-configuration qa runtime tasks workflows worktrees"
        ).split()
        index = (root / "functions.md").read_text()
        documented = []
        for family in families:
            name = f"functions-{family}.md"
            self.assertIn(f"]({name})", index)
            body = (root / name).read_text()
            owned = re.findall(r"^\| `([a-z_]+(?:\.[a-z_]+)+)` \|", body, re.M)
            mentioned = set(re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", body)) & expected
            self.assertEqual(mentioned, set(owned), name)
            documented.extend(owned)
        self.assertTrue(expected)
        self.assertEqual(set(documented), expected)
        self.assertEqual(set(Counter(documented).values()), {1})
        self.assertTrue(
            {"board.data.get", "doctor.run.run", "ephemeral_env.update"} <= expected
        )


class TestVersioningMetadata(_RegistryTestBase):
    """Registry preserves stability + replacement + removal_target_version."""

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

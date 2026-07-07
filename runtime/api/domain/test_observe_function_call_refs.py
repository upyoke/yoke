"""Unit tests for the function-call envelope recognizer."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from yoke_core.domain.observe_function_call_refs import (
    extract_function_call_item_id,
)


class TestExtractFunctionCallItemId(unittest.TestCase):
    def test_non_function_call_returns_none(self):
        self.assertIsNone(extract_function_call_item_id("ls -la"))
        self.assertIsNone(extract_function_call_item_id(""))
        self.assertIsNone(
            extract_function_call_item_id(
                "curl -X GET http://localhost:8000/v1/items/42"
            )
        )

    def test_inline_json_item_id(self):
        cmd = (
            'curl -X POST http://localhost:8000/v1/functions/call '
            '-d \'{"function":"items.progress_log.append",'
            '"target":{"kind":"item","item_id":1761}}\''
        )
        self.assertEqual(extract_function_call_item_id(cmd), "1761")

    def test_inline_json_no_item_id(self):
        cmd = (
            'curl -X POST http://localhost:8000/v1/functions/call '
            '-d \'{"function":"items.progress_log.append"}\''
        )
        self.assertIsNone(extract_function_call_item_id(cmd))

    def test_data_binary_file_reference(self):
        envelope = {
            "function": "items.structured_field.replace",
            "target": {"kind": "item", "item_id": 1761},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as handle:
            json.dump(envelope, handle)
            path = handle.name
        try:
            cmd = (
                f"curl -X POST http://localhost:8000/v1/functions/call "
                f"--data-binary @{path}"
            )
            self.assertEqual(extract_function_call_item_id(cmd), "1761")
        finally:
            os.unlink(path)

    def test_data_binary_short_dash_d_at_path(self):
        envelope = {"target": {"kind": "item", "item_id": 1761}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as handle:
            json.dump(envelope, handle)
            path = handle.name
        try:
            cmd = f"curl -X POST http://localhost:8000/v1/functions/call -d @{path}"
            self.assertEqual(extract_function_call_item_id(cmd), "1761")
        finally:
            os.unlink(path)

    def test_missing_file_returns_none(self):
        cmd = (
            "curl -X POST http://localhost:8000/v1/functions/call "
            "--data-binary @/tmp/this-does-not-exist-9k3hf.json"
        )
        self.assertIsNone(extract_function_call_item_id(cmd))

    def test_string_item_id_parsed(self):
        envelope = {"target": {"item_id": "1761"}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as handle:
            json.dump(envelope, handle)
            path = handle.name
        try:
            cmd = f"curl -X POST http://localhost:8000/v1/functions/call -d @{path}"
            self.assertEqual(extract_function_call_item_id(cmd), "1761")
        finally:
            os.unlink(path)

    def test_oversized_file_returns_none(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as handle:
            handle.write("x" * (17 * 1024))
            path = handle.name
        try:
            cmd = (
                f"curl -X POST http://localhost:8000/v1/functions/call "
                f"--data-binary @{path}"
            )
            self.assertIsNone(extract_function_call_item_id(cmd))
        finally:
            os.unlink(path)

    def test_malformed_json_file_returns_none(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as handle:
            handle.write("{not valid json")
            path = handle.name
        try:
            cmd = (
                f"curl -X POST http://localhost:8000/v1/functions/call "
                f"--data-binary @{path}"
            )
            self.assertIsNone(extract_function_call_item_id(cmd))
        finally:
            os.unlink(path)

    def test_target_missing_returns_none(self):
        envelope = {"function": "items.read"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as handle:
            json.dump(envelope, handle)
            path = handle.name
        try:
            cmd = f"curl -X POST http://localhost:8000/v1/functions/call -d @{path}"
            self.assertIsNone(extract_function_call_item_id(cmd))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

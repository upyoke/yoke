"""A union merge's output must be a document its own consumer would accept.

The shape under test is the one that broke a workflow in production: two
branches each added the same mapping key, the union kept both copies, and the
merge committed a file GitHub then refused outright. The decisive property is
that a plain parse check does NOT catch it — so the first test here pins the
lenient behaviour that made the incident possible, and the rest assert the
strict check that replaces it.
"""

from __future__ import annotations

import yaml

from yoke_core.domain import structured_file_validation as subject
from yoke_core.domain.yaml_helper import (
    DuplicateMappingKeyError,
    parse_documents_strictly,
)

# The union output from the incident: both sides added a yoke_dispatch_id
# input, so its three child keys each appear twice.
UNIONED_WORKFLOW = """\
on:
  workflow_dispatch:
    inputs:
      yoke_dispatch_id:
        description: correlation id
        required: false
        default: ''
        description: dispatch correlation id
        required: true
        default: none
"""

VALID_WORKFLOW = """\
on:
  workflow_dispatch:
    inputs:
      yoke_dispatch_id:
        description: correlation id
        required: false
        default: ''
"""


class TestParseAloneIsNotEnough:
    def test_the_lenient_loader_accepts_the_input_that_caused_the_incident(
        self,
    ) -> None:
        # Not an endorsement — this is the behaviour a "does it parse" check
        # would have inherited, and the reason this module exists. The top key
        # is ``True`` rather than ``"on"`` because YAML 1.1 reads a bare ``on``
        # as a boolean; GitHub reads the file its own way, which is one more
        # reason not to judge these files by what PyYAML makes of them.
        loaded = yaml.safe_load(UNIONED_WORKFLOW)
        entry = loaded[True]["workflow_dispatch"]["inputs"]["yoke_dispatch_id"]
        assert entry["required"] is True
        assert entry["description"] == "dispatch correlation id"

    def test_the_strict_loader_names_the_duplicate(self) -> None:
        try:
            parse_documents_strictly(UNIONED_WORKFLOW)
        except DuplicateMappingKeyError as exc:
            assert "description" in str(exc)
        else:
            raise AssertionError("duplicate mapping key was accepted")


class TestYaml:
    def test_a_duplicated_key_is_rejected(self) -> None:
        reason = subject.structured_document_error("ci.yml", UNIONED_WORKFLOW)
        assert reason is not None
        assert "description" in reason

    def test_a_valid_workflow_passes(self) -> None:
        assert subject.structured_document_error("ci.yml", VALID_WORKFLOW) is None

    def test_the_yaml_suffix_variant_is_also_read(self) -> None:
        assert subject.structured_document_error("ci.yaml", UNIONED_WORKFLOW)

    def test_unparseable_yaml_is_rejected(self) -> None:
        assert subject.structured_document_error("ci.yml", "a:\n  - [unclosed\n")

    def test_a_later_document_in_a_stream_is_still_read(self) -> None:
        stream = f"{VALID_WORKFLOW}---\n{UNIONED_WORKFLOW}"
        assert subject.structured_document_error("ci.yml", stream) is not None


class TestJson:
    def test_a_duplicated_key_is_rejected(self) -> None:
        reason = subject.structured_document_error(
            "packs.json", '{"slug": "a", "slug": "b"}'
        )
        assert reason is not None
        assert "slug" in reason

    def test_a_valid_document_passes(self) -> None:
        assert (
            subject.structured_document_error("packs.json", '{"slug": "a"}') is None
        )

    def test_unparseable_json_is_rejected(self) -> None:
        assert subject.structured_document_error("packs.json", "{")


class TestToml:
    def test_a_duplicated_key_is_rejected(self) -> None:
        assert subject.structured_document_error(
            "pyproject.toml", 'name = "a"\nname = "b"\n'
        )

    def test_a_valid_document_passes(self) -> None:
        assert (
            subject.structured_document_error("pyproject.toml", 'name = "a"\n')
            is None
        )


class TestUnrecognizedFormats:
    def test_append_oriented_text_is_left_alone(self) -> None:
        # No format to judge it against is the correct answer for the text the
        # union merge exists to serve; it must not become a refusal.
        assert subject.structured_document_error("shared-tests.sh", "{{{ not\n") is None
        assert not subject.is_structured_filename("shared-tests.sh")

    def test_structured_suffixes_are_recognized_case_insensitively(self) -> None:
        assert subject.is_structured_filename(".github/workflows/CI.YML")
        assert subject.is_structured_filename("packs.json")
        assert subject.is_structured_filename("pyproject.toml")

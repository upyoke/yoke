"""One delivery role serves every environment, so their grants merge into one.

The merge is where authority is quietly lost: a role that reaches production
and no longer reaches stage looks correct in the rendered descriptor and fails
only at the next stage deploy. These tests assert the union keeps everything
each environment stated, and still refuses what no environment may state.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.registry_delivery_authority_test_support import (
    STATED,
    environment,
    settings_for,
)

from yoke_core.domain import project_renderer_pulumi_ci as renderer


def _descriptor(*environments) -> dict:
    values = renderer.delivery_ci_values(settings_for(*environments))
    return json.loads(values["delivery_authority_json"])


class TestNothingStated:
    def test_a_project_that_states_nothing_renders_an_empty_descriptor(self) -> None:
        assert _descriptor(
            environment("prod", {"distribution": {"bucket_name": "b"}})
        ) == {}

    def test_an_environment_that_states_nothing_contributes_nothing(self) -> None:
        assert _descriptor(
            environment("stage", {}),
            environment("prod", {"delivery_authority": STATED}),
        ) == {
            "instance_tags": {"project": ["example"], "role": ["origin"]},
            "documents": ["AWS-RunShellScript"],
            "artifact_buckets": ["example-artifacts"],
            "artifact_key_prefixes": ["releases/"],
        }


class TestTheUnionKeepsEverythingStated:
    def test_grants_from_every_environment_are_merged(self) -> None:
        assert _descriptor(
            environment(
                "stage",
                {
                    "delivery_authority": {
                        "instance_tags": {"project": "example"},
                        "documents": ["AWS-RunShellScript"],
                        "artifact_buckets": ["example-artifacts"],
                        "artifact_key_prefixes": ["stage/"],
                    }
                },
            ),
            environment(
                "prod",
                {
                    "delivery_authority": {
                        "instance_tags": {"role": "origin"},
                        "documents": ["AWS-RunPowerShellScript"],
                        "artifact_buckets": ["example-artifacts"],
                        "artifact_key_prefixes": ["prod/"],
                    }
                },
            ),
        ) == {
            "instance_tags": {"project": ["example"], "role": ["origin"]},
            "documents": ["AWS-RunPowerShellScript", "AWS-RunShellScript"],
            "artifact_buckets": ["example-artifacts"],
            "artifact_key_prefixes": ["prod/", "stage/"],
        }

    def test_environments_naming_one_tag_key_differently_keep_both(self) -> None:
        # Assigning here would leave the role reaching whichever environment
        # merged last, the other silently stripped of SendCommand.
        assert _descriptor(
            environment(
                "stage",
                {"delivery_authority": {"instance_tags": {"Name": "stage-origin"}}},
            ),
            environment(
                "prod",
                {"delivery_authority": {"instance_tags": {"Name": "prod-origin"}}},
            ),
        )["instance_tags"] == {"Name": ["prod-origin", "stage-origin"]}

    def test_environments_keeping_separate_buckets_carry_both(self) -> None:
        assert _descriptor(
            environment(
                "stage",
                {"delivery_authority": {"artifact_buckets": ["example-stage"]}},
            ),
            environment(
                "prod",
                {"delivery_authority": {"artifact_buckets": ["example-prod"]}},
            ),
        )["artifact_buckets"] == ["example-prod", "example-stage"]

    def test_a_tag_key_may_be_stated_as_a_list_by_one_environment(self) -> None:
        assert _descriptor(
            environment(
                "prod",
                {
                    "delivery_authority": {
                        "instance_tags": {"Name": ["prod-origin", "stage-origin"]}
                    }
                },
            ),
        )["instance_tags"] == {"Name": ["prod-origin", "stage-origin"]}


class TestMisstatedSettingsAreRefused:
    def test_an_unknown_environment_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown delivery_authority keys"):
            _descriptor(
                environment("prod", {"delivery_authority": {"bucket": "one"}})
            )

    def test_a_descriptor_that_is_not_a_mapping_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must be a mapping"):
            _descriptor(environment("prod", {"delivery_authority": ["origin"]}))

    def test_instance_tags_that_are_not_a_mapping_are_refused(self) -> None:
        with pytest.raises(ValueError, match="instance_tags must be a mapping"):
            _descriptor(
                environment(
                    "prod", {"delivery_authority": {"instance_tags": ["Name=origin"]}}
                )
            )

    def test_buckets_stated_as_a_bare_string_are_refused(self) -> None:
        with pytest.raises(ValueError, match="artifact_buckets must be a list"):
            _descriptor(
                environment(
                    "prod",
                    {"delivery_authority": {"artifact_buckets": "example-prod"}},
                )
            )

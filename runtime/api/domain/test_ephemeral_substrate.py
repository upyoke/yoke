"""Tests for the canonical ephemeral substrate (slug/port/policy)."""

from __future__ import annotations

import pytest

from yoke_core.domain.ephemeral_substrate import (
    EPHEMERAL_TARGET_ENV,
    EphemeralPolicyError,
    compose_project_name,
    derive_port,
    ephemeral_deploy_dir,
    ephemeral_policy_from_capability,
    preview_url,
    slugify_branch,
)


class TestSlugifyBranch:
    def test_matches_github_actions_prepare_job_rules(self):
        assert slugify_branch("YOK-1369") == "yok-1369"
        assert slugify_branch("feature/foo bar") == "feature-foo-bar"
        assert slugify_branch("--X--Y--") == "x-y"
        assert slugify_branch("ephemeral substrate preview") == (
            "ephemeral-substrate-preview"
        )


class TestDerivePort:
    def test_golden_vectors_lock_the_cross_runtime_algorithm(self):
        """Literal expectations: parity with ephemeral_port.js and the GA
        prepare job (sha256(slug)[:8] hex % range + base). A refactor that
        drifts the algorithm breaks the wildcard router silently — these
        literals make it loud."""
        assert derive_port("yok-1369", 9000, 100) == 9077
        assert derive_port("yok-1369", 4000, 100) == 4077
        assert derive_port("ephemeral-substrate-preview", 9000, 100) == 9067
        assert derive_port("feature-foo-bar", 9000, 100) == 9076

    def test_rejects_nonpositive_range(self):
        with pytest.raises(EphemeralPolicyError):
            derive_port("x", 9000, 0)


class TestNaming:
    def test_compose_dir_url_shapes(self):
        assert compose_project_name("yoke", "abc") == "yoke-abc"
        assert ephemeral_deploy_dir("yoke", "abc") == "~/yoke-ephemeral/abc"
        assert preview_url("abc", "preview.example.com") == (
            "https://abc.preview.example.com"
        )
        assert EPHEMERAL_TARGET_ENV == "ephemeral"


def _cap(**overrides):
    cap = {
        "trigger": "flow",
        "host_env": "stage",
        "preview_domain": "preview.example.com",
        "api_base_port": 9000,
        "port_range": 100,
        "ttl_hours": 24,
    }
    cap.update(overrides)
    return cap


class TestPolicy:
    def test_full_flow_policy(self):
        policy = ephemeral_policy_from_capability("yoke", _cap())
        assert policy.trigger == "flow"
        assert policy.host_env == "stage"
        assert policy.preview_domain == "preview.example.com"
        assert policy.api_port_for("yok-1369") == 9077
        assert policy.web_base_port == 4000  # default fills in
        assert policy.ttl_hours == 24

    def test_github_push_policy_needs_no_host_env(self):
        policy = ephemeral_policy_from_capability(
            "buzz",
            _cap(trigger="github-push", host_env="",
                 preview_domain="buzzabuzz.com"),
        )
        assert policy.trigger == "github-push"
        assert policy.web_port_for("yok-1369") == 4077

    def test_missing_capability_fails_loudly(self):
        with pytest.raises(EphemeralPolicyError, match="ephemeral-env"):
            ephemeral_policy_from_capability("p", None)
        with pytest.raises(EphemeralPolicyError):
            ephemeral_policy_from_capability("p", {})

    def test_invalid_trigger_fails_loudly(self):
        with pytest.raises(EphemeralPolicyError, match="trigger"):
            ephemeral_policy_from_capability("p", _cap(trigger="cron"))
        with pytest.raises(EphemeralPolicyError, match="trigger"):
            ephemeral_policy_from_capability("p", _cap(trigger=""))

    def test_missing_preview_domain_fails_loudly(self):
        with pytest.raises(EphemeralPolicyError, match="preview_domain"):
            ephemeral_policy_from_capability("p", _cap(preview_domain=""))

    def test_flow_trigger_requires_host_env(self):
        with pytest.raises(EphemeralPolicyError, match="host_env"):
            ephemeral_policy_from_capability("p", _cap(host_env=""))

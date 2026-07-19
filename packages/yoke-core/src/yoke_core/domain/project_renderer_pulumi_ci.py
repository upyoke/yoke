"""GitHub Actions delivery inputs derived from renderer settings."""

from __future__ import annotations

from collections.abc import Mapping

from yoke_contracts.github_origin import DEFAULT_GITHUB_API_URL

from yoke_core.domain import json_helper
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
)


def delivery_ci_values(settings: ProjectRendererSettings) -> dict[str, str]:
    """Return exact distribution resources and App-key deny resources."""
    distribution_buckets: set[str] = set()
    cloudfront_distribution_ids: set[str] = set()
    app_key_secret_arns: set[str] = set()
    for environment in settings.environments:
        distribution = environment.settings.get("distribution")
        if isinstance(distribution, dict):
            bucket = str(distribution.get("bucket_name") or "").strip()
            if bucket:
                distribution_buckets.add(bucket)
        github_app = environment.settings.get("github_app")
        if isinstance(github_app, dict):
            secret_arn = str(github_app.get("private_key_secret_arn") or "").strip()
            if secret_arn:
                app_key_secret_arns.add(secret_arn)
    site_cdn = settings.site_settings.get("cdn")
    cdn_sources = (
        [site_cdn]
        if isinstance(site_cdn, Mapping)
        else [entry for entry in site_cdn if isinstance(entry, Mapping)]
        if isinstance(site_cdn, list)
        else []
    )
    domain_capability = settings.capabilities.get("domain")
    if isinstance(domain_capability, Mapping):
        cdn_sources.append(domain_capability)
    for source in cdn_sources:
        distribution_id = str(source.get("distribution_id") or "").strip()
        if distribution_id:
            cloudfront_distribution_ids.add(distribution_id)
        distribution_ids = source.get("distribution_ids")
        if isinstance(distribution_ids, list):
            cloudfront_distribution_ids.update(
                str(value).strip() for value in distribution_ids if str(value).strip()
            )
    github = settings.capabilities.get("github", {})
    return {
        "github_api_url": str(github.get("api_url") or DEFAULT_GITHUB_API_URL).strip(),
        "delivery_distribution_bucket_names_json": (
            json_helper.dumps_compact(sorted(distribution_buckets))
        ),
        "delivery_cloudfront_distribution_ids_json": (
            json_helper.dumps_compact(sorted(cloudfront_distribution_ids))
        ),
        "github_app_private_key_secret_arns_json": (
            json_helper.dumps_compact(sorted(app_key_secret_arns))
        ),
    }


__all__ = ["delivery_ci_values"]

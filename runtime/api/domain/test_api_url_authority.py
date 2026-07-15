from urllib.parse import urlsplit

from yoke_contracts.api_urls import (
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
    HEALTH_PATH,
    HOSTED_PROD_API_URL,
    HOSTED_STAGE_API_URL,
    join_api_url,
)


def test_hosted_control_apis_are_distinct_from_distribution_hosts() -> None:
    assert DISTRIBUTION_PROD_URL == "https://api.upyoke.com"
    assert DISTRIBUTION_STAGE_URL == "https://api.stage.upyoke.com"
    assert HOSTED_PROD_API_URL == (
        "https://app.upyoke.com/api/orgs/upyoke"
    )
    assert HOSTED_STAGE_API_URL == (
        "https://app.stage.upyoke.com/api/orgs/upyoke"
    )
    assert urlsplit(DISTRIBUTION_PROD_URL).netloc != urlsplit(
        HOSTED_PROD_API_URL
    ).netloc
    assert urlsplit(DISTRIBUTION_STAGE_URL).netloc != urlsplit(
        HOSTED_STAGE_API_URL
    ).netloc


def test_versioned_paths_join_to_tenant_scoped_control_api() -> None:
    assert join_api_url(HOSTED_PROD_API_URL, HEALTH_PATH) == (
        "https://app.upyoke.com/api/orgs/upyoke/v1/health"
    )
    assert join_api_url(HOSTED_STAGE_API_URL, HEALTH_PATH) == (
        "https://app.stage.upyoke.com/api/orgs/upyoke/v1/health"
    )

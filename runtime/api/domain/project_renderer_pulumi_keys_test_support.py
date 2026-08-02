"""The key set ``gather_pulumi_values`` is contracted to return.

Held beside the test rather than inside it: the set grows with every
rendered stack setting, and an inline literal would push the test file
past the authored-file line limit on the next addition.
"""

from __future__ import annotations

_GATHER_VALUES_KEYS = {
    "project_display_name",
    "project_slug",
    "PROJECT_NAME_UPPER",
    "project_description",
    "project_name",
    "deploy_namespace",
    "cloudfront_domain",
    "cloudfront_id",
    "certificate_arn",
    "hosted_zone_id",
    "aws_account_id",
    "vps_description",
    "domain_name",
    "origin_host",
    "origin_ip",
    "aws_region",
    "ssh_host",
    "ssh_user",
    "web_port",
    "api_port",
    "ephemeral_ttl_hours",
    "web_health_path",
    "web_smoke_paths",
    "domain",
    "api_port_base",
    "port_base",
    "port_range",
    "dns_provider",
    "preview_namespace",
    "preview_router_name",
    "preview_domain",
    "preview_route_port_base",
    "preview_web_port_base",
    "preview_port_range",
    "preview_ttl_hours",
    "configure_aws_credentials_action",
    "checkout_action",
}

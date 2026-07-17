# Webapp Template — Operations Notes

### Lessons Learned

Common pitfalls discovered during first deploys:

1. **CloudFront rejects IP origins.** Always use a domain name (e.g., `origin.example.com`) pointing to your VPS IP, never the IP directly.
2. **Don't let Pulumi create the hosted zone.** If a hosted zone already exists (e.g., from Route 53 domain registration), creating a new one in code produces a duplicate. The ACM cert validates against the duplicate zone (wrong NS delegation) and never issues. Always import existing zones via the `hosted_zone_id` stack config and `aws.route53.Zone.get(...)`.
3. **Don't let Pulumi create the ACM cert from scratch on first deploy.** Pulumi can wait synchronously for cert validation; if DNS isn't perfectly set up the stack hangs for hours then rolls back. Create the cert in the pre-flight step and import it via the `certificate_arn` stack config and `aws.acm.Certificate.get(...)`.
4. **Duplicate hosted zones are poison.** If you see two zones for the same domain, delete the one that doesn't match your registrar's NS records. DNS queries hit whichever zone the NS records point to.
5. **Open firewall ports before deploying.** CloudFront will return 504 if it can't reach your origin. Verify with `curl http://origin.example.com/` from your local machine before deploying.
6. **nginx is the right default.** Even if your app listens on `0.0.0.0:3000`, put nginx in front on port 80. It handles CloudFront's HTTP origin protocol cleanly and gives you a place to add headers, rate limiting, etc. later.

### Common Modifications

**Add MX records for email:**

Add MX records to `sites.settings.domains[].mx_records` for the relevant
domain, then refresh and apply the project Pulumi stack:

```json
{
  "id": "mailProvider",
  "name": "@",
  "priority": 10,
  "value": "mail.example.com",
  "ttl": 300
}
```

**Add a subdomain (e.g., api.example.com):**

Add a CNAME or A record pointing to your origin:

```python
aws.route53.Record(
    "api-subdomain",
    zone_id=hosted_zone.id,
    name=f"api.{domain_name}",
    type="CNAME",
    ttl=300,
    records=[origin_host],
)
```

**Enable caching for static assets:**

Replace the single `CachingDisabled` ordered cache behavior with additional ordered behaviors on the CloudFront distribution:

```python
ordered_cache_behaviors=[
    aws.cloudfront.DistributionOrderedCacheBehaviorArgs(
        path_pattern="/static/*",
        target_origin_id=origin_id,
        viewer_protocol_policy="redirect-to-https",
        cache_policy_id=managed_caching_optimized_id,
        allowed_methods=["GET", "HEAD", "OPTIONS"],
        cached_methods=["GET", "HEAD"],
    ),
],
```

**Preview changes before deploying:**

```sh
pulumi preview \
  --stack {{pulumi_infra_stack_name}} \
  --cwd <render-output>/infra
```

`pulumi preview` shows the diff between your local Pulumi program and the current stack state without applying changes.

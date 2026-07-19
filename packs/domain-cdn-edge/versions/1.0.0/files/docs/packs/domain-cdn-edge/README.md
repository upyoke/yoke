# Domain and CDN Edge Pack

Provides reusable Pulumi components for domains, DNS, API routing, CloudFront,
repository variables, and cache invalidation.

## Project-specific work

- Supply the domain, hosted zone, certificate, origin, distribution bucket,
  DNS records, and repository binding through project settings.
- Import existing resources before applying when the project is not new.
- Review origin access, cache policy, DNS ownership, and IAM permissions.
- Decide which application paths are static, dynamic, or excluded from cache.
- Record project-specific recovery and cutover steps in the project repository.

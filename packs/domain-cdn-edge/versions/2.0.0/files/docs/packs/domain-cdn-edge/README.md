# Domain and CDN Edge Pack

Provides reusable Pulumi components for domains, DNS, API routing, CloudFront,
repository variables, and cache invalidation.

## Stack files

The project checks in each stack's `infra/Pulumi.<stack>.yaml`; the Pulumi
Foundation Pack's `stacks.md` describes the convention and the `yoke:` values
Yoke adds. These stacks need only `yoke:github_access` unset (`metadata`).

A `<namespace>-domain` stack reads these `webapp-infra:` keys:

| Key | Required | Meaning |
|---|---|---|
| `domain_name` | yes | The apex domain |
| `import_zone_id` | no | Adopt this existing hosted zone instead of creating one |
| `manage_registration` | no, default `false` | Manage the domain registration too |
| `domain_txt_records` | no, default `[]` | JSON array of TXT records |
| `domain_mx_records` | no, default `[]` | JSON array of MX records |

A `<namespace>-infra` stack reads these `webapp-infra:` keys:

| Key | Required | Meaning |
|---|---|---|
| `domain_name` | yes | The apex domain |
| `origin_host` | yes | The origin hostname CloudFront forwards to |
| `hosted_zone_id` | yes | The hosted zone that holds the records |
| `origin_id` | yes | CloudFront origin Id; must equal a live imported distribution's |
| `certificate_arn` | no | An existing certificate to use |
| `distribution_bucket_name` | no | Static distribution bucket for `/install` and `/dist/*` |
| `distribution_origin_id` | no | Origin Id for that bucket |
| `domain_txt_records`, `domain_mx_records` | no, default `[]` | As above; leave them out when a domain stack owns the records |

Each TXT record is an object with `name` (default `@`), `value` or `values`,
optional `ttl` (default 300) and optional `resource_name`. Each MX record is
the same, with `priority` beside a single `value`, or `values` already written
as `"<priority> <host>"`.

## Project-specific work

- Supply the domain, hosted zone, certificate, origin, distribution bucket,
  and DNS records in the stack files above.
- Import existing resources before applying when the project is not new.
- Review origin access, cache policy, DNS ownership, and IAM permissions.
- Decide which application paths are static, dynamic, or excluded from cache.
- Record project-specific recovery and cutover steps in the project repository.

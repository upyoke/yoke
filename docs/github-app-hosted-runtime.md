# Hosted GitHub App runtime binding

Internal: server deployment configuration for Yoke maintainers. For self-hosted configuration, see [Server GitHub App setup](public/self-hosting/github-app.md).

Hosted/stage deployments use the same runtime contract but source the key from
AWS Secrets Manager. The deploy environment's `environments.settings` contains
only this non-secret reference block:

```json
{
  "github_app": {
    "issuer": "<numeric-app-id>",
    "api_url": "https://api.github.com",
    "private_key_secret_arn": "arn:aws:secretsmanager:<region>:<account>:secret:<name>",
    "public": {
      "client_id": "<public-client-id>",
      "app_slug": "<app-slug>",
      "app_id": 123456,
      "web_url": "https://github.com"
    }
  }
}
```

Omit `public` for a private/operator-only App that must never become the
default machine Connect profile. If `public` is present it must be complete;
the outer `api_url` is its single API-origin authority.
The origin instance role resolves that ARN locally. Deployment writes
`github-app-private-key.pem` as mode `0640`, owned by the deploy user and a
dedicated host secrets group, and grants only that numeric supplemental group
to the non-root container that mounts it at
`/dev/shm/yoke-runtime-secrets/yoke-github-app-private-key`. Secret values never cross SSH and
are not placed in Compose environment variables, command arguments, Pulumi
state, or project-engine databases.

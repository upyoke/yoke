# AUTO-GENERATED template source: templates/webapp/infra/webapp_registry_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource for the webapp container registry stack.

Provisions the per-PROJECT container image registry:

- One ECR repository per project (e.g. ``yoke-core``). Image artifacts are
  per-project, NOT per-environment: a single repository holds one image per
  git SHA (tags), and every environment of the project deploys by pulling a
  SHA tag from this shared registry. Deploy stages always pull from here —
  there is no per-env image build or per-env repository.
- A lifecycle policy that expires untagged images quickly and caps the tagged
  image history at the most recent 20, so the repository never accumulates
  unbounded storage from routine per-SHA pushes.
- GitHub Actions OIDC federation (when ``github_repo`` is set): the
  account-level ``token.actions.githubusercontent.com`` identity provider
  plus one assumable CI role trust-scoped to exactly that repository. CI
  authenticates with short-lived per-run STS credentials — no static access
  keys exist for CI. The registry stack is the natural home because CI is
  the registry's primary writer (image prewarm pushes) and every project
  with CI declares a registry. The provider is an ACCOUNT singleton: in a
  shared AWS account exactly one project's registry stack creates it
  (``manage_github_oidc_provider=True``); any other project declares False
  and the role references the provider by its well-known ARN.

The CI role carries ``AdministratorAccess``: Pulumi preview/apply over
stacks that manage VPC/EC2/RDS/Route53/CloudFront/ACM/ECR/KMS/S3 IS
infrastructure administration, so the hardening axis here is credential
lifetime + trust boundary (per-run tokens, single-repo trust), not policy
itemization. Scoping the policy below admin is a named tightening point.

``force_delete=True`` is the founder posture: a ``pulumi destroy`` of the
registry stack must not wedge on leftover images — the repository deletes
along with whatever it still holds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import pulumi
import pulumi_aws as aws


@dataclass
class WebappRegistryArgs:
    """Inputs for ``WebappRegistryStack``."""

    project_name: str
    # Full repository name (e.g. ``"yoke-core"``). The caller composes it;
    # no template-level default so the rendered config stays explicit.
    repository_name: str
    # GitHub repository slug (``owner/name``) trusted to assume the CI role.
    # Empty = render the registry without CI federation resources.
    github_repo: str = ""
    # Create the account-level GitHub OIDC provider (exactly one project per
    # AWS account may manage it; others reference it by ARN).
    manage_github_oidc_provider: bool = True
    # Required to compose the provider ARN when the provider is referenced
    # rather than created.
    aws_account_id: str = ""


# GitHub Actions OIDC issuer. The trust-policy condition keys derive from
# this host, and the referenced-provider ARN embeds it.
_GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"

# Long-published GitHub Actions OIDC CA thumbprints. AWS now pins trust for
# this provider itself and ignores the list, but the IAM API still requires
# at least one entry at create time.
_GITHUB_OIDC_THUMBPRINTS = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
]


def _github_trust_policy_json(provider_arn: str, github_repo: str) -> str:
    """Trust policy: only *github_repo*'s workflow runs may assume the role."""
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Federated": provider_arn},
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            f"{_GITHUB_OIDC_HOST}:aud": "sts.amazonaws.com",
                        },
                        "StringLike": {
                            f"{_GITHUB_OIDC_HOST}:sub": f"repo:{github_repo}:*",
                        },
                    },
                }
            ],
        }
    )


# Lifecycle policy: rule 1 expires untagged layers fast (they are only ever
# transient leftovers of a tag move under MUTABLE tagging); rule 2 keeps the
# most recent 20 tagged images (one tag per git SHA) and expires the rest.
def _lifecycle_policy_json() -> str:
    return json.dumps(
        {
            "rules": [
                {
                    "rulePriority": 1,
                    "description": "Expire untagged images after one day",
                    "selection": {
                        "tagStatus": "untagged",
                        "countType": "sinceImagePushed",
                        "countUnit": "days",
                        "countNumber": 1,
                    },
                    "action": {"type": "expire"},
                },
                {
                    "rulePriority": 2,
                    "description": "Keep only the most recent 20 tagged images",
                    "selection": {
                        "tagStatus": "tagged",
                        "tagPatternList": ["*"],
                        "countType": "imageCountMoreThan",
                        "countNumber": 20,
                    },
                    "action": {"type": "expire"},
                },
            ]
        }
    )


class WebappRegistryStack(pulumi.ComponentResource):
    """Per-project ECR repository with scan-on-push and bounded history."""

    repository: aws.ecr.Repository
    lifecycle_policy: aws.ecr.LifecyclePolicy

    def __init__(
        self,
        name: str,
        args: WebappRegistryArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__("webapp:infra:WebappRegistryStack", name, None, opts)

        tags = {"project": args.project_name}
        child_opts = pulumi.ResourceOptions(parent=self)

        # --- ECR repository ---
        # MUTABLE tags: deploy tooling may re-point convenience tags while the
        # per-SHA tags stay immutable by convention. ``force_delete`` lets a
        # stack destroy proceed even when images remain (founder posture).
        self.repository = aws.ecr.Repository(
            "containerRepository",
            name=args.repository_name,
            image_tag_mutability="MUTABLE",
            image_scanning_configuration=(
                aws.ecr.RepositoryImageScanningConfigurationArgs(
                    scan_on_push=True,
                )
            ),
            force_delete=True,
            tags=tags,
            opts=child_opts,
        )

        # --- Lifecycle policy: bounded image history ---
        self.lifecycle_policy = aws.ecr.LifecyclePolicy(
            "containerRepositoryLifecycle",
            repository=self.repository.name,
            policy=_lifecycle_policy_json(),
            opts=child_opts,
        )

        # --- GitHub Actions OIDC federation (optional) ---
        if args.github_repo:
            self._create_github_ci_role(args, tags, child_opts)

        # --- Exports for deploy stages and downstream stacks ---
        pulumi.export("containerRepositoryUrl", self.repository.repository_url)
        pulumi.export("containerRepositoryName", self.repository.name)
        pulumi.export("containerRegistryId", self.repository.registry_id)

        self.register_outputs(
            {
                "containerRepositoryUrl": self.repository.repository_url,
                "containerRepositoryName": self.repository.name,
                "containerRegistryId": self.repository.registry_id,
            }
        )

    def _create_github_ci_role(
        self,
        args: WebappRegistryArgs,
        tags: dict,
        child_opts: pulumi.ResourceOptions,
    ) -> None:
        """Provision the OIDC provider (or reference it) + the CI role."""
        if args.manage_github_oidc_provider:
            self.github_oidc_provider = aws.iam.OpenIdConnectProvider(
                "githubOidcProvider",
                url=f"https://{_GITHUB_OIDC_HOST}",
                client_id_lists=["sts.amazonaws.com"],
                thumbprint_lists=_GITHUB_OIDC_THUMBPRINTS,
                tags=tags,
                opts=child_opts,
            )
            provider_arn: pulumi.Input[str] = self.github_oidc_provider.arn
        else:
            if not args.aws_account_id:
                raise ValueError(
                    "manage_github_oidc_provider=False requires "
                    "aws_account_id to compose the provider ARN"
                )
            provider_arn = (
                f"arn:aws:iam::{args.aws_account_id}:"
                f"oidc-provider/{_GITHUB_OIDC_HOST}"
            )

        self.ci_role = aws.iam.Role(
            "githubActionsCiRole",
            name=f"{args.project_name}-ci-github",
            description=(
                f"GitHub Actions CI for {args.github_repo} "
                "(Pulumi preview/apply + ECR push; short-lived OIDC sessions)"
            ),
            assume_role_policy=pulumi.Output.from_input(provider_arn).apply(
                lambda arn: _github_trust_policy_json(arn, args.github_repo)
            ),
            tags=tags,
            opts=child_opts,
        )
        aws.iam.RolePolicyAttachment(
            "githubActionsCiAdmin",
            role=self.ci_role.name,
            policy_arn="arn:aws:iam::aws:policy/AdministratorAccess",
            opts=child_opts,
        )
        pulumi.export("githubActionsCiRoleArn", self.ci_role.arn)

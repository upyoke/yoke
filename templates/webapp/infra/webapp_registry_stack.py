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

OIDC authority is split into two roles. The infrastructure role is preview-
only: ViewOnlyAccess plus exact state reads and immutable privilege/secret
denies. All applies remain operator-attended through local ``aws-admin``
authority, so repository code cannot rewrite its own custody boundary. The
delivery role has an inline action/resource policy for release operations.

``force_delete=True`` is the founder posture: a ``pulumi destroy`` of the
registry stack must not wedge on leftover images — the repository deletes
along with whatever it still holds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import pulumi
import pulumi_aws as aws


@dataclass
class WebappRegistryArgs:
    """Inputs for ``WebappRegistryStack``."""

    deploy_namespace: str
    # Full repository name (e.g. ``"yoke-core"``). The caller composes it;
    # no template-level default so the rendered config stays explicit.
    repository_name: str
    # GitHub repository slug (``owner/name``) trusted to assume the CI role.
    # Empty = render the registry without CI federation resources.
    github_repo: str = ""
    github_api_url: str = "https://api.github.com"
    # Create the account-level GitHub OIDC provider (exactly one project per
    # AWS account may manage it; others reference it by ARN).
    manage_github_oidc_provider: bool = True
    # Required to compose the provider ARN when the provider is referenced
    # rather than created.
    aws_account_id: str = ""
    state_bucket: str = ""
    kms_key_alias: str = ""
    distribution_bucket_names: list[str] = field(default_factory=list)
    cloudfront_distribution_ids: list[str] = field(default_factory=list)
    github_app_private_key_secret_arns: list[str] = field(default_factory=list)


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


def _github_trust_policy_json(
    provider_arn: str,
    github_repo: str,
    *,
    allowed_branches: tuple[str, ...] = (),
    allowed_environments: tuple[str, ...] = (),
) -> str:
    """Trust only exact branch or environment subjects for one repository."""
    subjects = [
        f"repo:{github_repo}:ref:refs/heads/{branch}"
        for branch in allowed_branches
    ]
    subjects.extend(
        f"repo:{github_repo}:environment:{environment}"
        for environment in allowed_environments
    )
    if not subjects:
        raise ValueError("GitHub OIDC trust requires at least one exact subject")
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
                            f"{_GITHUB_OIDC_HOST}:sub": subjects,
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

        tags = {"project": args.deploy_namespace}
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
        if not args.state_bucket or not args.kms_key_alias:
            raise ValueError(
                "GitHub CI roles require state_bucket and kms_key_alias"
            )
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

        self.infrastructure_role = aws.iam.Role(
            "githubActionsCiRole",
            name=f"{args.deploy_namespace}-ci-github",
            description=(
                f"GitHub Actions infrastructure preview for {args.github_repo} "
                "(non-mutating Pulumi refresh/preview; short-lived OIDC sessions)"
            ),
            assume_role_policy=pulumi.Output.from_input(provider_arn).apply(
                lambda arn: _github_trust_policy_json(
                    arn,
                    args.github_repo,
                    allowed_branches=("main",),
                )
            ),
            tags=tags,
            opts=child_opts,
        )
        aws.iam.RolePolicyAttachment(
            "githubActionsInfrastructureViewOnly",
            role=self.infrastructure_role.name,
            policy_arn=(
                "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess"
            ),
            opts=child_opts,
        )
        self.delivery_role = aws.iam.Role(
            "githubActionsDeliveryRole",
            name=f"{args.deploy_namespace}-delivery-ci-github",
            description=(
                f"GitHub Actions delivery for {args.github_repo} "
                "(no infrastructure or GitHub App key authority)"
            ),
            assume_role_policy=pulumi.Output.from_input(provider_arn).apply(
                lambda arn: _github_trust_policy_json(
                    arn,
                    args.github_repo,
                    allowed_branches=("main",),
                    allowed_environments=("stage", "production"),
                )
            ),
            tags=tags,
            opts=child_opts,
        )
        from webapp_registry_ci_policy import (
            delivery_policy_json,
            infrastructure_preview_policy_json,
        )

        caller = aws.get_caller_identity()
        region = aws.get_region()
        state_key = aws.kms.get_alias(name=args.kms_key_alias)
        aws.iam.RolePolicy(
            "githubActionsInfrastructureBoundary",
            role=self.infrastructure_role.id,
            policy=infrastructure_preview_policy_json(
                region=region.name,
                account_id=caller.account_id,
                state_bucket=args.state_bucket,
                kms_key_arn=state_key.target_key_arn,
                deploy_namespace=args.deploy_namespace,
                distribution_bucket_names=args.distribution_bucket_names,
                github_app_private_key_secret_arns=(
                    args.github_app_private_key_secret_arns
                ),
            ),
            opts=child_opts,
        )
        aws.iam.RolePolicy(
            "githubActionsDeliveryPolicy",
            role=self.delivery_role.id,
            policy=delivery_policy_json(
                region=region.name,
                account_id=caller.account_id,
                deploy_namespace=args.deploy_namespace,
                state_bucket=args.state_bucket,
                kms_key_arn=state_key.target_key_arn,
                distribution_bucket_names=args.distribution_bucket_names,
                cloudfront_distribution_ids=args.cloudfront_distribution_ids,
                github_app_private_key_secret_arns=(
                    args.github_app_private_key_secret_arns
                ),
            ),
            opts=child_opts,
        )
        pulumi.export(
            "githubActionsInfrastructureRoleArn", self.infrastructure_role.arn
        )
        pulumi.export("githubActionsDeliveryRoleArn", self.delivery_role.arn)
        from webapp_registry_github_variables import create_ci_role_variables

        (
            self.infrastructure_role_variable,
            self.delivery_role_variable,
        ) = create_ci_role_variables(
            github_repo=args.github_repo,
            github_api_url=args.github_api_url,
            infrastructure_role_arn=self.infrastructure_role.arn,
            delivery_role_arn=self.delivery_role.arn,
            child_opts=child_opts,
        )
        # Retained during the additive rollout so the existing role is never
        # replaced before repository variables point at the two new outputs.
        pulumi.export("githubActionsCiRoleArn", self.infrastructure_role.arn)

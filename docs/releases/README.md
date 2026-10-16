# Yoke release notes

This guide covers release creation and provenance verification. Release notes
are the immutable annotated tag messages, published with the corresponding
GitHub Releases; this directory contains no per-release notes.

## Cut a release

The registered `github.release.create_commit_tag` operation creates an annotated
`BASE.YYYYMMDDHHMM` tag from the exact source commit's UTC committer clock.
Its CLI is `yoke github release create-commit-tag OWNER/REPO SOURCE-SHA
--summary TEXT --project P`; consult `--help` before use.
A retry recovers the same annotated tag. A tag naming another commit, including
another commit in the same UTC minute, refuses without moving the ref; create
a new source commit with a distinct minute before retrying.
The operation has a declared serving floor. Verify the carrying API is served
before activating callers; the hosted bridge uses this operation directly.

1. Verify and merge the exact source on `main`. Bind the consumer commit through
   the selected release flow; follow the [source-dev release rules](../source-dev-doctrine.md).
2. The hosted bridge reuses the passed proof of that exact product/consumer pair
   across stage and production. A different commit pair needs its own proof.
   The bridge passes the registered `stage` or `prod` environment unchanged.
3. Treat release tags as immutable. The scoped GitHub App creates the annotated
   tag and immutable release note.
   `0.2.0.202610140941` is an example of the canonical spelling: base version
   `0.2.0` plus the source commit's UTC committer minute, without a `v` prefix.
   Tag, wheel metadata, image reference and displayed release version agree.
4. `yoke-release` downloads the successful `main` push's wheel artifact for the
   exact source SHA. It verifies manifest size/hash, package metadata, migration
   identity and GitHub attestations bound to the main ref, source SHA and signer.
   It rechecks the annotated tag immediately before publishing the same bytes
   as GitHub Release assets. Missing, expired or failed factory output refuses
   with a recovery; publication never rebuilds it or substitutes another SHA.

The `main` wheel factory uses `uv run python -m yoke_core.tools.build_release`,
pins all product
siblings to the shared version and resolves its product roots from explicit
local wheel paths. Numeric version spelling alone does not establish origin;
installers and relay installs select product bytes from the declared distribution.
Public indexes supply third-party dependencies.

The image factory builds and verifies native linux/amd64 and linux/arm64 images
on `main`, assembles their manifest and signs its digest in a no-checkout job.
The tag job downloads that successful exact-main record and verifies its OCI
attestation before promoting the same digest to `:VERSION`. It refuses a
conflicting immutable version reference. Serialized publication advances `latest`
only for the highest canonical annotated release, so retrying an older release
cannot roll it back. Main pushes never update release pointers.
Merge-queue candidates check both native image builds with read-only permissions,
without registry publication or signing.

Both main factory artifacts retain their provenance records for 14 days. If
those workflow artifacts expire, rerun the exact main factory and then retry
publication; do not rerun a tag-time build or create a cache.

## First public image publication

GHCR creates the first container package as private even when it is linked to
a public repository. After the first successful image run, a package admin must
open the `upyoke/yoke-server` package settings and explicitly change its
visibility to **Public**. Repository visibility alone is not sufficient. Do not
call the image launch complete until a clean, unauthenticated registry client
can pull the exact digest and its registry-stored attestation verifies against
the main ref and full source commit.

Use this smoke from a machine with Docker, buildx, `curl`, `jq`, `gh`, and no
required GHCR login. Replace only the tag value; the remaining identity is
resolved from the public GitHub REST API and remote annotated tag:

```bash
tag="0.2.0.202610140941"
repository="ghcr.io/upyoke/yoke-server"
api="https://api.github.com/repos/upyoke/yoke/git"
tag_object="$(curl -fsSL -H 'Accept: application/vnd.github+json' \
  "$api/ref/tags/$tag" | jq -er '.object.sha')"
source_sha="$(curl -fsSL -H 'Accept: application/vnd.github+json' \
  "$api/tags/$tag_object" | jq -er '.object.sha')"
version="$tag"
digest="<sha256:digest-from-the-completed-image-run>"

anonymous_config="$(mktemp -d)"
trap 'rm -rf "$anonymous_config"' EXIT
DOCKER_CONFIG="$anonymous_config" docker pull --platform linux/amd64 \
  "$repository:$version"
DOCKER_CONFIG="$anonymous_config" docker pull --platform linux/arm64 \
  "$repository:$version"
DOCKER_CONFIG="$anonymous_config" docker pull "$repository:latest"
sha_digest="$(DOCKER_CONFIG="$anonymous_config" docker buildx imagetools inspect \
  "$repository:$version" --format '{{ .Manifest.Digest }}')"
latest_digest="$(DOCKER_CONFIG="$anonymous_config" docker buildx imagetools inspect \
  "$repository:latest" --format '{{ .Manifest.Digest }}')"
test "$sha_digest" = "$digest"
test "$latest_digest" = "$digest"
manifest="$(DOCKER_CONFIG="$anonymous_config" docker buildx imagetools inspect \
  "$repository:$version" --format '{{json .Manifest}}')"
platforms="$(jq -r \
  '[.manifests[]?.platform | select(.os != "unknown") | "\(.os)/\(.architecture)"] | unique | sort | join(",")' \
  <<< "$manifest")"
test "$platforms" = "linux/amd64,linux/arm64"
DOCKER_CONFIG="$anonymous_config" gh attestation verify \
  "oci://$repository@$digest" \
  --bundle-from-oci \
  --repo upyoke/yoke \
  --signer-workflow upyoke/yoke/.github/workflows/yoke-server-image.yml \
  --source-ref refs/heads/main \
  --source-digest "$source_sha" \
  --deny-self-hosted-runners
```

The launch receipt records the package settings URL with Public visibility,
workflow-run URL, annotated tag-object SHA, peeled source SHA, image digest,
successful digest equality, both anonymous platform pulls, the exact
linux/amd64+linux/arm64 manifest, and exact-source attestation output.
Never record registry credentials or Docker configuration contents.

## Verify provenance

Download a wheel from the GitHub Release, then verify both its bytes and the
GitHub-hosted signer workflow:

```bash
release_ref="refs/heads/main"
release_sha="<full-40-character-release-commit-sha>"
gh attestation verify ./yoke_core-*.whl \
  --repo upyoke/yoke \
  --signer-workflow upyoke/yoke/.github/workflows/yoke-build-artifacts.yml \
  --source-ref "$release_ref" \
  --source-digest "$release_sha" \
  --deny-self-hosted-runners
```

For later releases, resolve or copy the immutable image digest from the
completed image workflow and verify that digest rather than `latest`:

```bash
image_tag="0.2.0.202610140941"
image_sha="<full-40-character-release-commit-sha>"
gh attestation verify \
  oci://ghcr.io/upyoke/yoke-server@sha256:<digest> \
  --bundle-from-oci \
  --repo upyoke/yoke \
  --signer-workflow upyoke/yoke/.github/workflows/yoke-server-image.yml \
  --source-ref refs/heads/main \
  --source-digest "$image_sha" \
  --deny-self-hosted-runners
```

The wheel manifest and package-index hashes remain useful transport-integrity
checks. The GitHub attestations add the authenticated claim tying those bytes
to this repository, source commit, workflow, and GitHub-hosted build identity.

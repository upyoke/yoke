# Yoke release notes

This directory is the authored source for public GitHub Release notes. It
starts at the first release made through the current release factory; older
tags are deliberately not backfilled with reconstructed history.

## Cut a release

1. Choose the next version `X.Y.Z+local.N` and add a matching
   `docs/releases/vX.Y.Z+local.N.md` on `main`. The PEP 440 local segment is
   intentional: public indexes cannot publish local versions, which keeps a
   same-named public package from satisfying Yoke's exact sibling pins. Use a
   short lowercase label such as `build.1`; the file must be nonempty and
   begin with `# Yoke X.Y.Z+local.N`. Write for operators and users: name
   visible changes, upgrade steps, and compatibility breaks. Do not paste
   ticket chronology or internal planning provenance.
2. Run the canonical test gate on that exact commit and merge it to `main`.
3. Create an annotated `vX.Y.Z+local.N` tag at the verified main commit and
   push only that tag. Treat release tags as immutable: never move or recreate
   one after pushing it. Use canonical decimal atoms: `v1.2.3+launch.1` is
   valid, while release or numeric-local atoms with leading zeros are refused.
   The `yoke-release` workflow resolves the remote tag
   object and its peeled commit before the build and again immediately before
   publication. It refuses lightweight or moved tags, tags without the required
   local segment, commits not reachable from current `main`, missing/mismatched
   notes, or a wheel version that differs from the tag.
4. The workflow calls `yoke-build-artifacts`, which builds and validates the
   four product wheels in a read-only job, then transfers the validated tree to
   a no-checkout signer job that signs those exact wheel bytes. Only after the
   final job verifies the manifest, bytes, signer workflow, exact tag ref, and
   exact source commit does it create the GitHub Release with the wheels,
   `release-records.json`, and the authored note.

A new note can start from this shape:

```markdown
# Yoke X.Y.Z+local.N

## Highlights

Describe the user-visible outcome.

## Upgrade notes

State required actions, or say that the normal update path is sufficient.

## Compatibility

Name API, server/CLI, schema, or self-host compatibility changes. Say `None`
when there are none.
```

The SHA12 server image is a separate, repository-variable-gated factory lane.
Arm `YOKE_PUBLISH_SERVER_IMAGE` before pushing the annotated release tag when
image publication is intended. The tag push is the only trigger: branch pushes
and ad hoc dispatches cannot move `latest` to a development version. If the
variable was not armed, set it and choose **Re-run all jobs** on that tag's
existing `yoke-server-image` run; never recreate or move the tag.

The image workflow independently verifies the remote annotated tag, its exact
peeled commit, and current-main reachability. It pushes unnamed content by
digest, signs that digest from a no-checkout job, and only then exposes
`:<sha12>` and `:latest`. Publication refuses an existing `:<sha12>` that points
to different bytes and verifies both names resolve to the signed digest.

## First public image publication

GHCR creates the first container package as private even when it is linked to
a public repository. After the first successful image run, a package admin must
open the `upyoke/yoke-server` package settings and explicitly change its
visibility to **Public**. Repository visibility alone is not sufficient. Do not
call the image launch complete until a clean, unauthenticated registry client
can pull the exact digest and its registry-stored attestation verifies against
the release tag and full source commit.

Use this smoke from a machine with Docker, buildx, `curl`, `jq`, `gh`, and no
required GHCR login. Replace only the tag value; the remaining identity is
resolved from the public GitHub REST API and remote annotated tag:

```bash
tag="vX.Y.Z+local.N"
repository="ghcr.io/upyoke/yoke-server"
api="https://api.github.com/repos/upyoke/yoke/git"
tag_object="$(curl -fsSL -H 'Accept: application/vnd.github+json' \
  "$api/ref/tags/$tag" | jq -er '.object.sha')"
source_sha="$(curl -fsSL -H 'Accept: application/vnd.github+json' \
  "$api/tags/$tag_object" | jq -er '.object.sha')"
sha12="${source_sha:0:12}"
digest="<sha256:digest-from-the-completed-image-run>"

anonymous_config="$(mktemp -d)"
trap 'rm -rf "$anonymous_config"' EXIT
DOCKER_CONFIG="$anonymous_config" docker pull --platform linux/amd64 \
  "$repository:$sha12"
DOCKER_CONFIG="$anonymous_config" docker pull --platform linux/arm64 \
  "$repository:$sha12"
DOCKER_CONFIG="$anonymous_config" docker pull "$repository:latest"
sha_digest="$(DOCKER_CONFIG="$anonymous_config" docker buildx imagetools inspect \
  "$repository:$sha12" --format '{{ .Manifest.Digest }}')"
latest_digest="$(DOCKER_CONFIG="$anonymous_config" docker buildx imagetools inspect \
  "$repository:latest" --format '{{ .Manifest.Digest }}')"
test "$sha_digest" = "$digest"
test "$latest_digest" = "$digest"
manifest="$(DOCKER_CONFIG="$anonymous_config" docker buildx imagetools inspect \
  "$repository:$sha12" --format '{{json .Manifest}}')"
platforms="$(jq -r \
  '[.manifests[]?.platform | select(.os != "unknown") | "\(.os)/\(.architecture)"] | unique | sort | join(",")' \
  <<< "$manifest")"
test "$platforms" = "linux/amd64,linux/arm64"
DOCKER_CONFIG="$anonymous_config" gh attestation verify \
  "oci://$repository@$digest" \
  --bundle-from-oci \
  --repo upyoke/yoke \
  --signer-workflow upyoke/yoke/.github/workflows/yoke-server-image.yml \
  --source-ref "refs/tags/$tag" \
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
release_ref="refs/tags/vX.Y.Z+local.N"
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
image_tag="vX.Y.Z+local.N"
image_sha="<full-40-character-release-commit-sha>"
gh attestation verify \
  oci://ghcr.io/upyoke/yoke-server@sha256:<digest> \
  --bundle-from-oci \
  --repo upyoke/yoke \
  --signer-workflow upyoke/yoke/.github/workflows/yoke-server-image.yml \
  --source-ref "refs/tags/$image_tag" \
  --source-digest "$image_sha" \
  --deny-self-hosted-runners
```

The wheel manifest and package-index hashes remain useful transport-integrity
checks. The GitHub attestations add the authenticated claim tying those bytes
to this repository, source commit, workflow, and GitHub-hosted build identity.

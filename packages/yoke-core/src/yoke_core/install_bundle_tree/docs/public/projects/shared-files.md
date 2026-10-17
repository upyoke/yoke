# Shared Files

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Projects](index.md) > Shared files
<!-- /yoke:breadcrumbs -->

Upload a file, get a URL that stays valid, and paste it anywhere: an item
field, a strategy doc, a chat message. Every authorized client of the same
universe reads the same bytes through Yoke. Yoke keeps no record of the
file; the project and path are its whole address.

## Upload and use

```sh
yoke files upload ./review.html --path plans/review.html
# https://<server>/v1/files/<project>/plans/review.html
```

`files.upload` needs `items.write` on the project. The project comes from
`--project`, `YOKE_PROJECT`, or the current checkout's mapping. `--path`
defaults to the file name. A path is 1 to 16 `/`-separated segments; each
segment starts with a letter or digit and uses only letters, digits, `.`, `_`
or `-`. Uploading to an existing path replaces that file. Files are limited
to 20 MiB. `--json` returns `url`, `backend`, `address`, `bytes` and
`sha256`.

Open the URL with `items.read` on the project:

- **Browser:** open the file URL. A signed-out or expired browser goes to
  sign-in and returns to that URL afterward, including `?download=1`.
  Without company sign-in, run `yoke ui up` from your terminal on a
  connected machine to open admission in the same browser. Local views use
  the same command on their own machine. The file renders inline by default.
- **Agent or script:** send the connection's API token as
  `Authorization: Bearer`.

The type comes from the extension: HTML, Markdown and JSON are served as
UTF-8 text, and unknown extensions as `application/octet-stream`. Pages are
served inside a sandbox (`Content-Security-Policy: sandbox`). Their scripts
run, but never as the reader's signed-in Yoke session.

## Where the bytes live

| Universe | Storage | URL base |
|---|---|---|
| Project environment declares `artifacts.bucket` | That bucket, under `shared-files/<project>/<path>`; signed with the project's `aws-admin` capability | Connection `api_url` |
| No bucket declared | The serving machine's permanent tree: `~/.yoke/shared-files/<project>/<path>` | Connection `api_url` |
| Hosted | The tenant's artifacts bucket, through the hosted storage signer, under the tenant's prefix | Hosted `api_url` |
| Local mode | Same rules as above, on this machine | `http://127.0.0.1:8688`, while `yoke ui` serves on its default port |

Every read signs a fresh, short-lived store URL on the server. The returned
link does not depend on any signed URL and stays valid while the file exists.
Shared files never expire, the same as QA evidence: artifact buckets carry no
expiry rule for either, and the permanent local tree keeps files until someone
deletes them.

## Failures

API and CLI requests keep a structured 401 when credentials are absent or
invalid; browser navigation redirects to sign-in. An explicit
`Authorization` header always selects API authentication.

Each refusal carries a code and the step that fixes it:

| Code | Meaning and recovery |
|---|---|
| `shared_file_path_invalid` | A segment breaks the path rule. Rename the path. |
| `permission_denied` | Uploading needs `items.write` on the project. |
| `project_not_found` | The project does not exist, or you lack `items.read` on it. |
| `shared_file_not_found` | Nothing is stored at that path. Check the URL or upload the file again. |
| `shared_file_not_portable` | This connection reaches a universe that another server serves, and the project has no bucket. Upload through the https connection that serves the universe. |
| `s3_configuration_invalid` | The bucket is declared but the `aws-admin` region or credentials are missing. Set them. |
| `s3_upload_failed`, `s3_download_failed`, `artifact_broker_*` | The configured store failed. Yoke never falls back to disk. Retry after the store recovers. |
| `function_version_skew` | The server predates `files.upload`. Upgrade the serving build. |

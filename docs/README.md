# Yoke documentation

| Tree | Audience | Installed into projects? | On upyoke.com/docs? |
|---|---|---|---|
| **`docs/public/`** | Operators + agents | Yes → `.yoke/docs/` | Yes |
| **`docs/`** (outside `public/`) | Yoke source-dev / contributors | No | No |
| **`docs/archive/`** | Historical | No | No |

In the Yoke source repository, author operator docs only under `docs/public/`.
Refresh the dogfood mirror and packaged snapshot with:

```bash
yoke dev run -- python3 -m yoke_core.domain.install_bundle_tree_sync sync --target-root <checkout>
```

`<checkout>` must be a Yoke source checkout. Other targets refuse with
`install_bundle_target_not_yoke_source` before creating files or directories.
Installed projects refresh their managed files with `yoke project install`.

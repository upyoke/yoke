# Snapshot Primitives

Source-development diagnostics for the browser daemon. QA execution goes
through the registered `yoke qa` surfaces; these commands record no verdict.

### Accessibility Snapshot

Produces a structured accessibility tree (Playwright's `page.accessibility.snapshot()`) with stable ref IDs on each element.

```sh
python3 -m yoke_core.domain.browser_client snapshot accessibility <url>
```

Output: JSON with `{ tree, refs, url, timestamp }`.

### Annotated Screenshot

Captures a page screenshot with numbered ref badges overlaid on interactive elements.

```sh
python3 -m yoke_core.domain.browser_client snapshot screenshot <url> [--annotate] [--output <path>] [--viewport <WxH>]
```

Output: JSON with `{ imagePath, refs }`. The `refs` map associates integer ref IDs with Playwright locator strings.

### Diff Snapshot

Captures a screenshot and compares it against a baseline image using pixel-level diff (pixelmatch).

```sh
python3 -m yoke_core.domain.browser_client snapshot diff <url> --baseline <path> --viewport <WxH> \
 [--output-dir <dir>] [--threshold <N>]
```

Output: JSON with `{ diff_pct, diff_image_path, candidate_path, baseline_path, viewport }`. When no baseline exists: `{ diff_pct: null, missing_baseline: true, candidate_path }`.


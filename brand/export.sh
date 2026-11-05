#!/usr/bin/env bash
# Run from any directory; librsvg and ImageMagick must be on PATH.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
for tool in rsvg-convert magick; do
  if ! command -v "$tool" >/dev/null; then
    printf 'brand_export_tool_missing: install librsvg and ImageMagick, then rerun brand/export.sh (%s missing).\n' "$tool" >&2
    exit 1
  fi
done
assets="$root/brand/favicon"
for pair in apple-touch-icon:180 icon-192:192 icon-512:512; do
  name="${pair%:*}"
  size="${pair#*:}"
  rsvg-convert -w "$size" -h "$size" --keep-aspect-ratio \
    "$assets/favicon.svg" -o "$assets/$name.png"
done
rsvg-convert "$assets/og-image.svg" -o "$assets/og-image.png"
magick -background none "$assets/favicon.svg" -define icon:auto-resize=64,48,32,16 \
  "$assets/favicon.ico"
ui="$root/packages/yoke-core/src/yoke_core/ui/static"
cp "$root/brand/theme.css" "$root/brand/shell.css" "$ui/"
cp "$root/brand/logo/yoke.svg" "$root/brand/logo/yoke-wordmark.svg" "$ui/"
cp "$assets/favicon.svg" "$assets/favicon.ico" "$assets/apple-touch-icon.png" \
  "$assets/icon-192.png" "$assets/icon-512.png" "$assets/og-image.svg" \
  "$assets/og-image.png" "$assets/site.webmanifest" "$ui/"

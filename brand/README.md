# Yoke brand

Canonical source for every Yoke logo, wordmark, favicon, and shared design tokens.
Consumers **copy** from here — the marketing site copies from its pinned checkout
of this repo, and Yoke's universe app copies locally. Generic Packs deliberately
contain no Yoke branding; another project supplies its own assets after installing
a UI Pack. Never fork the Yoke mark inside this repo; change it here and update
Yoke-owned consumers.

## What the mark means

The mark encodes the product. The **Y-joint** (`#yoke-connector`) is the **core** —
the synthesis point everything is drawn into. The **base triangle** (`#yoke-triangle`)
is **strategy**, the foundation (drawn first in the build animation, last to leave).
The **two arm-rings** (`#yoke-ring-left`, `#yoke-ring-right`) are two **parallel
execution** work items. Strategy foundation -> parallel execution.

## Files

- `logo/yoke.svg` — the mark. `currentColor`, four ids intact; recolor via CSS.
- `logo/yoke-wordmark.svg` — the unchanged icon as Y, followed by outlined O, K, E
  from Martian Mono 200. Orange icon; letters mix 30% icon with 70% ink.
  The em bearings are O .0772/.0772, K .1632/.0804, E .1658/.1008;
  optical gaps are .08, .125, .115em. O scales by .8/.828 around the cap middle.
  Paths keep the lockup identical when loaded as an image without external fonts.
- `favicon/favicon.svg` — the orange mark, legible on the Steel background.
- `favicon/og-image.svg` — the wordmark on a 1200x630 canvas; source for the OG PNG.
- `favicon/site.webmanifest` — PWA metadata.
- `favicon/*.png`, `favicon/favicon.ico` — raster derivatives materialized from the
  SVGs (browsers/social need raster). Regenerate them if you change the mark.
- `theme.css` — design tokens (CSS variables). The single knob for color/type/radius.
- `shell.css` — the shared application-header frame and its structural tokens.

## Customizing

Steel orange follows the system light or dark preference. A root `data-theme="light"`
or `data-theme="dark"` overrides that preference. Light uses background `#f7f8fa`,
ink `#202830`, orange text `#994600` and blue text `#24618f`; dark retains
background `#101418`, ink `#dfe6ec`, orange `#f4a261` and blue `#a5d8ff`.
Corners are square. Filled controls use `--yoke-accent-fill` (`#f4a261`) with
`--yoke-accent-fill-ink` (`#101418`); text uses the theme's `--yoke-accent`.
Wordmark letters inherit the host's text colour when embedded inline.
Fira Code sets display and
mono text; Fira Sans sets body text. The UI self-hosts WOFF2 fonts with system
fallbacks, loaded by `ui/static/fonts.css`, and OFL notices in `ui/static/fonts-OFL.txt`; upstream sources are
[Google Fonts](https://github.com/google/fonts/tree/main/ofl) (firacode, firasans,
martianmono). Consumer stylesheets load their adjacent `fonts.css`, keeping font
URLs correct under both local and hosted asset prefixes. Public docs carry the
same font bytes embedded in their generated `fonts.css`: installed docs use a
text bundle. `brand/export.sh` refreshes that CSS from the UI WOFF2 sources and
includes the complete OFL notices in its leading comment. Docs assets permit CSS,
SVG and HTML files, so no separate license text file is published there.
Martian Mono is retained for live brand text.

The repository permits this source asset exporter as its sole `.sh` file.

Install librsvg and ImageMagick, then run `yoke dev run -- bash brand/export.sh`.
The script exports square PNG icons (scaled uniformly and padded transparently)
and multi-size ICO files with `rsvg-convert` and `magick`,
then copies all canonical brand files byte-for-byte into the UI static directory.
It preserves the source SVG geometry; OG and wordmark lettering is already paths.

## Deferred

Color/mono logo variants, geometry `params.json`, and the v2 animation
(swirl -> crystallize -> strategy-triangle -> execution-rings) live outside the repo
for now; the animation is a hero/loading candidate, brought in later as SVG/Lottie
source under `motion/`, never as large rendered GIFs.

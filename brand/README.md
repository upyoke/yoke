# Yoke brand

Canonical source for every Yoke logo, wordmark, favicon, and (later) animation.
Consumers **copy** from here — the marketing site (platform repo) copies from its
pinned checkout of this repo; the universe app and the webapp template copy locally.
The managed webapp copy lives under
`templates/webapp/scaffold/app/web/public/brand/`; its global stylesheet loads
that copied `theme.css`, and parity tests refuse consumer drift.
Never fork the mark; change it here and let consumers follow.

## What the mark means

The mark encodes the product. The **Y-joint** (`#yoke-connector`) is the **core** —
the synthesis point everything is drawn into. The **base triangle** (`#yoke-triangle`)
is **strategy**, the foundation (drawn first in the build animation, last to leave).
The **two arm-rings** (`#yoke-ring-left`, `#yoke-ring-right`) are two **parallel
execution** work items. Strategy foundation -> parallel execution.

## Files

- `logo/yoke.svg` — the mark. `currentColor`, four ids intact; recolor via CSS.
- `logo/yoke-wordmark.svg` — icon + "Yoke" lockup. Live text (provisional font);
  change the `font-family` / weight / the word in one line. Used in both site navs.
- `favicon/favicon.svg` — the mark with adaptive ink (light/dark via media query).
- `favicon/og-image.svg` — the wordmark on a 1200x630 canvas; source for the OG PNG.
- `favicon/site.webmanifest` — PWA metadata.
- `favicon/*.png`, `favicon/favicon.ico` — raster derivatives materialized from the
  SVGs (browsers/social need raster). Regenerate them if you change the mark.
- `theme.css` — design tokens (CSS variables). The single knob for color/type/radius.

## Customizing

Everything here is provisional and meant to be changed: edit the SVGs directly,
swap the wordmark font, or retune `theme.css`. The raster derivatives are the only
generated outputs — re-export them from the SVGs after a change.

## Deferred

Color/mono logo variants, geometry `params.json`, and the v2 animation
(swirl -> crystallize -> strategy-triangle -> execution-rings) live outside the repo
for now; the animation is a hero/loading candidate, brought in later as SVG/Lottie
source under `motion/`, never as large rendered GIFs.

# Getting started visual adaptations

The teaching prototype adapts Platform artwork as responsive HTML and SVG.
The illustrations contain example project data, not live product state.
They are authored here so the prototype remains self-contained and readable
at document width; Platform remains unchanged.

Source paths below are relative to the Platform repository:

| Section | Source | Adaptation |
| --- | --- | --- |
| Installation | `webapp/src/components/marketing-install.tsx` and `install-command.tsx` | Agent request and guided setup conversation |
| Universes and hosting | `docs/ux/yoke-film/film-5.js` and `webapp/src/components/marketing-hosting.tsx` | Same three hosting icons, with a universe containing projects |
| Strategy | `webapp/src/components/marketing-strategy-graphic.tsx` | Standing document cards and a steered CURRENT-PLAN, using its storefront example |
| Work | `docs/ux/yoke-film/film-4.js` | Item, agent claim and isolated worktree, with an illustrative stage strip |
| Sessions | `webapp/src/components/marketing-sessions-graphic.tsx` | Steering session connected to three workers, with condensed example cards |
| QA | `docs/ux/yoke-film/film-4.js` | Evidence scene's tests, browser check, review and approval sequence |
| Deployments | `webapp/src/components/marketing-ops-graphics.tsx` | Release run with QA complete and approval pending |
| Operations | `webapp/src/components/marketing-ouroboros.tsx` | Field notes → curation → steering learning cycle |

The examples omit volatile model names, usage totals and invented test counts.
Figures use semantic text with captions; decorative hosting icons are hidden
from assistive technology. No autoplay or motion is needed to read them.

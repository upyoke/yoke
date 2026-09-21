// The evidence behind a decision, shown as pictures first.
//
// A screenshot is a thumbnail the reviewer can see before they click; a
// stored command output or log is one chip that opens as text. Both read
// their bytes through `qa.artifact.read` — the same authorized read QA
// detail uses — and both say plainly when the bytes are not here: a capture
// that lives on another machine, a read that failed, a file too large to
// inline. Nothing is drawn from a count alone.

import {
  appendMoreDisclosure,
} from "./universe_sessions_holdings_disclosure.js";
import {
  artifactCaption,
  artifactHandle,
  artifactLabel,
  artifactLocation,
  artifactStepLabel,
  normalizeArtifact,
} from "./qa_evidence_artifact_view.js";
import {
  decodeText,
  readArtifact,
  readOutcome,
} from "./review_evidence_read.js";
import { openImageLightbox, openTextLightbox } from "./review_lightbox.js";
import {
  el,
  portabilityMode,
} from "./universe_view_support.js";

// How many artifacts a strip shows before it folds the rest behind "+N
// more". A release whose checks captured two dozen screenshots is real, and
// a wall of them is not a strip.
export const EVIDENCE_SHOWN = 6;

// A tile has three states, not two. `is-ready` and `is-unavailable` are the
// settled pair; between mount and settle the bytes are still being read, and
// that window is not brief — a strip reads one artifact per tile, and a
// release card carrying several runs reads them all at once. The window has
// to draw something, because the picture carries this slot's frame and
// background and stays hidden until it has a source: with nothing in its
// place a reader gets a caption under blank space and cannot tell a tile
// that is still loading from one whose bytes never arrived.
const PENDING_STATE = "Loading evidence…";

function isImage(artifact) {
  return String(artifact.content_type || "").startsWith("image/")
    || artifact.artifact_type.toLowerCase().includes("screenshot");
}

// The title a reader hovers or opens: what the capture recorded about the
// picture, then where the bytes live. The location is here and not on the
// caption, so one screenshot does not print somebody's home directory under
// every thumbnail in every section that shows it.
function captionOf(artifact) {
  return [
    artifactCaption(artifact) || artifactLabel(artifact),
    artifactLocation(artifact),
  ].filter(Boolean).join(" — ");
}

// What the caption reads: the step this picture was taken at, or the
// artifact's own name when the capture recorded no step.
//
// `stepCaptionsOnly` drops that fallback, for the surfaces where a picture
// rides inside a card rather than standing on its own: a stored filename
// under a 104px thumbnail names the file rather than the moment, wraps to
// two lines at that width, and repeats under every picture in the strip.
// The identity is not lost there — it stays the image's alt text and the
// figure's title, and the full artifact detail is one press away in the
// viewer. A surface whose subject IS the artifact keeps the name.
function shotLabel(artifact, stepCaptionsOnly) {
  const step = artifactStepLabel(artifact);
  const named = step || (stepCaptionsOnly ? "" : artifactLabel(artifact));
  const parts = [artifact.owner_ref, artifact.provenance, named].filter(Boolean);
  return parts.join(" · ");
}

// The pending box says why it is empty instead of the reason the read
// failed; the node itself is the same one either way, so a tile never shows
// two states at once and never loses its frame between them.
function markUnavailable(figure, state, outcome) {
  figure.classList.remove("is-pending");
  figure.classList.add("is-unavailable");
  state.textContent = outcome.state;
  if (outcome.detail) figure.title = outcome.detail;
}

// A screenshot: the picture and its caption are two links to the same
// evidence, so each one opens this artifact and nothing around it. They are
// real anchors rather than a widget spelled with a role, which is what gives
// them focus, Enter, and a middle-click that opens the bytes in a tab. The
// long caption the capture recorded stays on the figure's title, where it
// tells the reader which picture this is without becoming four lines of
// metadata under a thumbnail.
function screenshot(context, artifact, stepCaptionsOnly) {
  const documentNode = context.document;
  const caption = captionOf(artifact);
  const figure = el(documentNode, "figure", "review-shot");
  figure.setAttribute("data-artifact-id", String(artifact.id));
  if (artifact.provenance) {
    figure.setAttribute("data-provenance", artifact.provenance);
  }
  if (caption) figure.title = caption;
  const picture = el(documentNode, "a", "review-shot-open");
  const image = el(documentNode, "img", "review-shot-image");
  image.alt = caption;
  picture.appendChild(image);
  figure.classList.add("is-pending");
  // Inside the picture, not beside it: the state box IS this tile's frame
  // while there is no picture to be one, so the caption that follows sits
  // against the tile it names instead of below the space a hidden image
  // was holding open.
  const state = el(documentNode, "span", "review-shot-state", PENDING_STATE);
  picture.appendChild(state);
  figure.appendChild(picture);
  const label = shotLabel(artifact, stepCaptionsOnly);
  const step = label
    ? el(documentNode, "a", "review-shot-step", label) : null;
  if (step) {
    const figcaption = el(documentNode, "figcaption", "review-shot-caption");
    figcaption.appendChild(step);
    figure.appendChild(figcaption);
  }
  void readArtifact(context, artifact).then((response) => {
    if (context.isMounted && !context.isMounted()) return;
    const outcome = readOutcome(response);
    if (!outcome.ready) {
      markUnavailable(figure, state, outcome);
      return;
    }
    picture.removeChild(state);
    figure.classList.remove("is-pending");
    image.src = outcome.source;
    figure.classList.add("is-ready");
    const open = (event) => {
      if (typeof event.preventDefault === "function") event.preventDefault();
      if (typeof event.stopPropagation === "function") event.stopPropagation();
      openImageLightbox(documentNode, outcome.source, caption);
    };
    for (const control of [picture, step].filter(Boolean)) {
      control.href = outcome.source;
      control.target = "_blank";
      control.rel = "noopener";
      control.setAttribute("aria-label", `Open full size: ${caption}`);
      control.addEventListener("click", open);
    }
  });
  return figure;
}

// Text evidence — command output, a log, a transcript excerpt — is one chip
// that opens the stored text in place. Bytes held elsewhere open in a new
// tab instead, because a presigned object is not something this page can
// read into a block.
function textChip(context, artifact) {
  const documentNode = context.document;
  const label = artifactLabel(artifact);
  const chip = el(documentNode, "button", "review-text-chip");
  chip.type = "button";
  chip.setAttribute("data-artifact-id", String(artifact.id));
  chip.appendChild(el(documentNode, "span", "review-text-chip-label", `≡ ${label}`));
  chip.appendChild(el(
    documentNode,
    "small",
    "review-text-chip-kind",
    String(artifact.artifact_type).replaceAll("_", " "),
  ));
  chip.addEventListener("click", async () => {
    if (chip.disabled) return;
    chip.disabled = true;
    const outcome = readOutcome(await readArtifact(context, artifact));
    chip.disabled = false;
    if (!outcome.ready) {
      chip.classList.add("is-unavailable");
      chip.children[1].textContent = outcome.state;
      return;
    }
    if (outcome.base64 !== undefined) {
      openTextLightbox(documentNode, label, decodeText(outcome.base64));
      return;
    }
    const view = documentNode.defaultView;
    if (view && typeof view.open === "function") view.open(outcome.href, "_blank");
  });
  return chip;
}

function onMachineChip(documentNode, artifact) {
  const chip = el(documentNode, "span", "review-text-chip is-unavailable");
  chip.appendChild(el(
    documentNode, "span", "review-text-chip-label", `≡ ${artifactLabel(artifact)}`,
  ));
  chip.appendChild(el(
    documentNode, "small", "review-text-chip-kind", "on its capture machine",
  ));
  return chip;
}

// `artifacts` accepts either shape callers hold — QA rows keyed `id`, gate
// projections keyed `artifact_id` — and `requirementId` fills in for
// projections that carry none of their own. An artifact whose identity does
// not normalize is not drawable and is dropped here rather than downstream.
export function normalizedArtifacts(artifacts, options = {}) {
  return (Array.isArray(artifacts) ? artifacts : [])
    .map((raw) => ({
      ...normalizeArtifact(raw, options.requirementId),
      provenance: raw.provenance ?? null,
    }))
    .filter((artifact) => Number.isFinite(artifact.id));
}

// What a strip actually puts on screen for these options: the same rows, cut
// at the same limit, because everything past it is folded behind "+N more"
// and is not visible until someone clicks. A caller that suppresses its own
// evidence as "already shown" has to mean exactly this set — meaning the
// whole input instead hides a request's evidence that was never drawn.
export function drawnArtifacts(artifacts, options = {}) {
  return normalizedArtifacts(artifacts, options)
    .slice(0, options.limit ?? EVIDENCE_SHOWN);
}

export function evidenceStrip(context, artifacts, options = {}) {
  const documentNode = context.document;
  const rows = normalizedArtifacts(artifacts, options);
  if (!rows.length) {
    if (!options.emptyNote) return null;
    const none = el(documentNode, "div", "review-evidence-none", options.emptyNote);
    none.setAttribute("role", "note");
    return none;
  }
  const strip = el(
    documentNode,
    "div",
    `review-evidence${options.compact ? " compact" : ""}`,
  );
  const hosted = portabilityMode(context.capabilities) === "hosted";
  const draw = (artifact) => {
    const local = artifactHandle(artifact)?.backend === "local";
    if (hosted && local) return onMachineChip(documentNode, artifact);
    if (isImage(artifact)) {
      return screenshot(context, artifact, options.stepCaptionsOnly);
    }
    return textChip(context, artifact);
  };
  const limit = options.limit ?? EVIDENCE_SHOWN;
  for (const artifact of rows.slice(0, limit)) strip.appendChild(draw(artifact));
  const rest = rows.slice(limit);
  if (rest.length) {
    // Opened AND closable: expanding used to consume the control, so a strip
    // of twenty screenshots could be widened but never narrowed again.
    // Hidden remainder is not drawn until expanded, so folded screenshots
    // do not issue `qa.artifact.read` while they cannot be seen.
    const region = el(documentNode, "div", "review-evidence-rest");
    region.setAttribute("role", "region");
    region.setAttribute("aria-label", "More evidence");
    strip.appendChild(region);
    const button = appendMoreDisclosure(documentNode, strip, {
      key: `evidence:${rows.map((artifact) => artifact.id).join(",")}`,
      hiddenCount: rest.length,
      region,
      className: "review-more",
    });
    const fill = () => {
      if (region.children.length) return;
      for (const artifact of rest) region.appendChild(draw(artifact));
    };
    if (!region.hidden) fill();
    button.addEventListener("click", () => { if (!region.hidden) fill(); });
  }
  return strip;
}

export const reviewEvidenceStrip = {
  drawnArtifacts,
  evidenceStrip,
  normalizedArtifacts,
};

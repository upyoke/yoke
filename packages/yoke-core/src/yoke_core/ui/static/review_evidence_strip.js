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
import { openImageLightbox, openTextLightbox } from "./review_lightbox.js";
import {
  callFunction,
  el,
  portabilityMode,
} from "./universe_view_support.js";

const READ_TIMEOUT_MS = 15_000;

// How many artifacts a strip shows before it folds the rest behind "+N
// more". A release whose checks captured two dozen screenshots is real, and
// a wall of them is not a strip.
export const EVIDENCE_SHOWN = 6;

const UNAVAILABLE_STATES = {
  evidence_on_machine: (result) => `On ${result.machine || "its capture machine"}`,
  evidence_not_portable: () => "Not portable",
  too_large: () => "Too large to show",
  unavailable: () => "Image unavailable",
};

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
  if (step) return step;
  return stepCaptionsOnly ? "" : artifactLabel(artifact);
}

function decodeText(base64) {
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function artifactReads(context) {
  if (!context.artifactReads) context.artifactReads = new Map();
  return context.artifactReads;
}

function abortWhenObsolete(context, abort) {
  if (typeof context.isMounted !== "function") return () => {};
  const timer = setInterval(() => {
    if (!context.isMounted()) abort();
  }, 25);
  return () => clearInterval(timer);
}

async function readArtifact(context, artifact, signal) {
  const reads = artifactReads(context);
  const key = `${artifact.requirement_id}:${artifact.id}`;
  const existing = reads.get(key);
  if (existing) return existing;
  let timer;
  const controller = typeof AbortController === "function"
    ? new AbortController() : null;
  const onAbort = () => controller?.abort();
  if (signal?.aborted) onAbort();
  else signal?.addEventListener("abort", onAbort, { once: true });
  const stopWatch = abortWhenObsolete(context, onAbort);
  const pending = Promise.race([
    callFunction(
      context.client,
      "qa.artifact.read",
      { artifact_id: artifact.id },
      { kind: "qa_requirement", qa_requirement_id: artifact.requirement_id },
      controller ? { signal: controller.signal } : undefined,
    ),
    new Promise((_, reject) => {
      const fail = (error) => reject(error);
      timer = setTimeout(() => {
        fail(new Error("Evidence read timed out. Retry."));
        onAbort();
      }, context.evidenceReadTimeoutMs || READ_TIMEOUT_MS);
      const aborted = () => fail(new Error("Evidence read aborted."));
      controller?.signal.addEventListener("abort", aborted, { once: true });
      if (controller?.signal.aborted) aborted();
    }),
  ]).catch((error) => ({
    status: 0,
    envelope: { success: false, error: { message: String(error?.message || error) } },
  })).finally(() => {
    clearTimeout(timer);
    stopWatch();
    signal?.removeEventListener?.("abort", onAbort);
    if (reads.get(key) === pending) reads.delete(key);
  });
  reads.set(key, pending);
  return pending;
}

function readOutcome(response) {
  if (response.status !== 200 || !response.envelope?.success) {
    return {
      ready: false,
      state: response.envelope?.error?.message || "Evidence unavailable",
    };
  }
  const result = response.envelope.result || {};
  const disposition = result.disposition || "unavailable";
  if (disposition !== "ready") {
    const describe = UNAVAILABLE_STATES[disposition] || UNAVAILABLE_STATES.unavailable;
    return { ready: false, state: describe(result), detail: result.detail || "" };
  }
  const contentType = result.content_type || "";
  if (typeof result.content_base64 === "string") {
    return {
      ready: true,
      source: `data:${contentType || "application/octet-stream"};base64,${result.content_base64}`,
      base64: result.content_base64,
      href: null,
    };
  }
  if (result.download_url) {
    return { ready: true, source: result.download_url, href: result.download_url };
  }
  return { ready: false, state: "Evidence unavailable" };
}

function markUnavailable(documentNode, figure, outcome) {
  figure.classList.add("is-unavailable");
  figure.appendChild(el(
    documentNode, "span", "review-shot-state", outcome.state,
  ));
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
  if (caption) figure.title = caption;
  const picture = el(documentNode, "a", "review-shot-open");
  const image = el(documentNode, "img", "review-shot-image");
  image.alt = caption;
  picture.appendChild(image);
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
      markUnavailable(documentNode, figure, outcome);
      return;
    }
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
    .map((raw) => normalizeArtifact(raw, options.requirementId))
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

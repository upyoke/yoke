// The evidence behind a decision, shown as pictures first.
//
// A screenshot is a thumbnail the reviewer can see before they click; a
// stored command output or log is one chip that opens as text. Both read
// their bytes through `qa.artifact.read` — the same authorized read QA
// detail uses — and both say plainly when the bytes are not here: a capture
// that lives on another machine, a read that failed, a file too large to
// inline. Nothing is drawn from a count alone.

import {
  artifactCaption,
  artifactHandle,
  artifactLabel,
  normalizeArtifact,
} from "./qa_evidence_artifact_view.js";
import { openImageLightbox, openTextLightbox } from "./review_lightbox.js";
import {
  callFunction,
  el,
  portabilityMode,
} from "./universe_view_support.js";

const READ_TIMEOUT_MS = 15_000;

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

function captionOf(artifact) {
  return artifactCaption(artifact) || artifactLabel(artifact);
}

function decodeText(base64) {
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

async function readArtifact(context, artifact) {
  let timer;
  try {
    return await Promise.race([
      callFunction(
        context.client,
        "qa.artifact.read",
        { artifact_id: artifact.id },
        { kind: "qa_requirement", qa_requirement_id: artifact.requirement_id },
      ),
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error("Evidence read timed out. Retry.")),
          context.evidenceReadTimeoutMs || READ_TIMEOUT_MS,
        );
      }),
    ]);
  } catch (error) {
    return {
      status: 0,
      envelope: { success: false, error: { message: String(error) } },
    };
  } finally {
    clearTimeout(timer);
  }
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

// A screenshot: the thumbnail is the control. It loads at once, because a
// picture the reviewer has to ask for is a picture they will judge without.
function screenshot(context, artifact) {
  const documentNode = context.document;
  const caption = captionOf(artifact);
  const figure = el(documentNode, "figure", "review-shot");
  figure.setAttribute("data-artifact-id", String(artifact.id));
  const image = el(documentNode, "img", "review-shot-image");
  image.alt = caption;
  figure.appendChild(image);
  figure.appendChild(el(documentNode, "figcaption", "review-shot-caption", caption));
  void readArtifact(context, artifact).then((response) => {
    const outcome = readOutcome(response);
    if (!outcome.ready) {
      markUnavailable(documentNode, figure, outcome);
      return;
    }
    image.src = outcome.source;
    figure.classList.add("is-ready");
    figure.setAttribute("role", "button");
    figure.tabIndex = 0;
    figure.setAttribute("aria-label", `Open full size: ${caption}`);
    const open = () => openImageLightbox(documentNode, outcome.source, caption);
    figure.addEventListener("click", open);
    figure.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") open();
    });
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
// projections that carry none of their own.
export function evidenceStrip(context, artifacts, options = {}) {
  const documentNode = context.document;
  const rows = (Array.isArray(artifacts) ? artifacts : [])
    .map((raw) => normalizeArtifact(raw, options.requirementId))
    .filter((artifact) => Number.isFinite(artifact.id));
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
  for (const artifact of rows) {
    const local = artifactHandle(artifact)?.backend === "local";
    if (hosted && local) {
      strip.appendChild(onMachineChip(documentNode, artifact));
    } else if (isImage(artifact)) {
      strip.appendChild(screenshot(context, artifact));
    } else {
      strip.appendChild(textChip(context, artifact));
    }
  }
  return strip;
}

export const reviewEvidenceStrip = { evidenceStrip };

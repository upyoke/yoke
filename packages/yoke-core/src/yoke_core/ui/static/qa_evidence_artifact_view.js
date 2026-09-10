// One artifact reader, drawn the same way everywhere a person judges QA
// evidence.
//
// Somebody asked to record a verdict on a screenshot is answering the same
// question from the Inbox, from a deployment run card, and from QA detail,
// so all three read the bytes through `qa.artifact.read` and draw the answer
// here. The gate surfaces used to draw type-and-count chips instead: an
// approver was told that three screenshots existed and given no way to look
// at any of them, which is a verdict asked for on evidence its reader never
// saw.
//
// Loading stays an explicit act. An Inbox listing every pending gate would
// otherwise fetch every artifact of every row on paint, and evidence bytes
// run to megabytes; the card names what it holds, and reads it when asked.

import {
  callFunction,
  el,
  portabilityMode,
} from "./universe_view_support.js";

// Callers hold an artifact in two shapes -- QA detail reads whole rows off a
// case result, while a gate carries the narrower projection its subject
// context validates -- so both normalize here rather than teaching the
// renderer two sets of field names.
export function normalizeArtifact(raw, requirementId = null) {
  return {
    id: Number(raw.id ?? raw.artifact_id),
    artifact_type: String(raw.artifact_type || "artifact"),
    content_type: raw.content_type ?? null,
    artifact_handle: raw.artifact_handle ?? null,
    metadata: raw.metadata ?? null,
    requirement_id: Number(raw.requirement_id ?? requirementId),
  };
}

function artifactMetadata(artifact) {
  const raw = artifact.metadata;
  if (!raw) return null;
  if (typeof raw === "object") return raw;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

// The caption a capture already recorded about itself. Four screenshots of
// one page at four steps are the same filename to a reader; the route, step
// and viewport are what tell them apart, and the capture wrote them down.
export function artifactCaption(artifact) {
  const meta = artifactMetadata(artifact);
  if (!meta) return "";
  const viewport = meta.viewport
    ? `${meta.viewport.width}×${meta.viewport.height}`
    : "";
  return [
    meta.label,
    meta.route,
    meta.step_index === undefined || meta.step_index === null
      ? ""
      : `step ${meta.step_index}`,
    viewport,
    meta.browser,
  ].filter(Boolean).join(" · ");
}

export function artifactHandle(artifact) {
  if (!artifact.artifact_handle) return null;
  if (typeof artifact.artifact_handle === "object") {
    return artifact.artifact_handle;
  }
  try {
    const handle = JSON.parse(artifact.artifact_handle);
    return handle && typeof handle === "object" ? handle : null;
  } catch {
    return null;
  }
}

export function artifactLabel(artifact) {
  const handle = artifactHandle(artifact);
  if (!handle) return artifact.artifact_type;
  const key = handle.key ? String(handle.key).split("/").at(-1) : null;
  return handle.filename || key || handle.path || artifact.artifact_type;
}

// What a gate card knows about storage before it reads anything. A gate
// projection carries no handle, so it says what it does know -- the artifact
// kind -- rather than asserting a backend it cannot see; the read itself
// then reports the real disposition.
function artifactStorage(artifact, hostedLocal) {
  const handle = artifactHandle(artifact);
  if (handle?.backend === "s3") {
    return "s3 handle · rendered via presigned read";
  }
  if (handle?.backend === "local") {
    return hostedLocal
      ? "local handle — on this machine only; viewable where it was " +
        "captured, not from this browser"
      : "local handle · available only from its capture machine";
  }
  if (!handle) {
    return artifact.content_type
      ? `${artifact.artifact_type} · ${artifact.content_type}`
      : artifact.artifact_type;
  }
  return "typed artifact handle";
}

// A hosted browser cannot reach a capture machine's filesystem, so a local
// handle read from one is stated as unreachable up front instead of being
// offered as a control that can only fail.
function isHostedLocal(context, artifact) {
  return portabilityMode(context.capabilities) === "hosted"
    && artifactHandle(artifact)?.backend === "local";
}

function isImage(contentType) {
  return String(contentType || "").startsWith("image/");
}

// The preview and the full-size view are one control: the reader clicks what
// they are looking at, and a screenshot too small to judge at card scale
// opens at its own size in a new tab.
function appendImage(documentNode, host, source, label) {
  const full = el(documentNode, "a", "qa-evidence-full");
  full.href = source;
  full.target = "_blank";
  full.rel = "noopener";
  full.setAttribute("aria-label", `Open full image: ${label}`);
  const image = el(documentNode, "img", "qa-evidence-preview");
  image.src = source;
  image.alt = label;
  full.appendChild(image);
  full.appendChild(el(
    documentNode, "span", "qa-evidence-full-label", "open full image ↗",
  ));
  host.appendChild(full);
}

// Renders one read result and returns the short state the action control
// should carry, or null when the evidence itself is now on screen.
export function showArtifactResult(documentNode, host, artifact, result) {
  host.replaceChildren();
  const disposition = result.disposition || "unavailable";
  const label = artifactLabel(artifact);
  if (disposition !== "ready") {
    const state = {
      evidence_on_machine: `on ${result.machine || "capture machine"}`,
      evidence_not_portable: "not portable",
      too_large: "too large",
      unavailable: "unavailable",
    }[disposition] || "unavailable";
    if (result.detail) {
      host.appendChild(el(
        documentNode, "span", "qa-evidence-state", result.detail,
      ));
    }
    return state;
  }
  const contentType = result.content_type || artifact.content_type;
  if (typeof result.content_base64 === "string") {
    const source = `data:${contentType || "application/octet-stream"};base64,${result.content_base64}`;
    if (isImage(contentType)) {
      appendImage(documentNode, host, source, label);
    } else {
      const link = el(documentNode, "a", "qa-evidence-link", "open →");
      link.href = source;
      link.download = label;
      host.appendChild(link);
    }
    return null;
  }
  if (!result.download_url) {
    return "unavailable";
  }
  // A stored screenshot is evidence whichever backend holds it. Presigned
  // reads used to stop at a bare link, so hosted reviewers judged S3
  // evidence by filename while local reviewers saw the picture.
  if (isImage(contentType)) {
    appendImage(documentNode, host, result.download_url, label);
    return null;
  }
  const link = el(documentNode, "a", "qa-evidence-link", "view →");
  link.href = result.download_url;
  link.target = "_blank";
  link.rel = "noopener";
  host.appendChild(link);
  return null;
}

export function artifactEvidenceCard(context, raw, requirementId = null) {
  const documentNode = context.document;
  const artifact = normalizeArtifact(raw, requirementId);
  const hostedLocal = isHostedLocal(context, artifact);
  const label = artifactLabel(artifact);
  const card = el(documentNode, "div", "qa-evidence");
  card.appendChild(el(documentNode, "span", "qa-evidence-icon", "🖼"));
  const copy = el(documentNode, "span");
  const open = el(
    documentNode,
    hostedLocal ? "span" : "button",
    hostedLocal ? "mono" : "qa-evidence-open",
    label,
  );
  if (!hostedLocal) open.type = "button";
  copy.appendChild(open);
  copy.appendChild(el(
    documentNode, "small", null, artifactStorage(artifact, hostedLocal),
  ));
  const caption = artifactCaption(artifact);
  if (caption) {
    copy.appendChild(el(documentNode, "small", "qa-evidence-caption", caption));
  }
  if (hostedLocal) {
    card.appendChild(copy);
    card.appendChild(el(
      documentNode,
      "span",
      "qa-evidence-action qa-evidence-state",
      "on-machine",
    ));
    return card;
  }
  const resultHost = el(documentNode, "div", "qa-evidence-result");
  copy.appendChild(resultHost);
  card.appendChild(copy);
  const action = el(
    documentNode,
    "button",
    "qa-evidence-open qa-evidence-action",
    "view →",
  );
  action.type = "button";
  action.setAttribute("aria-label", `View ${label}`);
  action.style.color = "var(--yoke-link)";
  card.appendChild(action);
  const load = async () => {
    open.disabled = true;
    action.disabled = true;
    action.textContent = "loading…";
    action.style.color = "var(--yoke-muted)";
    resultHost.textContent = "loading evidence…";
    let response;
    try {
      response = await callFunction(
        context.client,
        "qa.artifact.read",
        { artifact_id: artifact.id },
        {
          kind: "qa_requirement",
          qa_requirement_id: artifact.requirement_id,
        },
      );
    } catch (error) {
      response = {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
    if (response.status === 200 && response.envelope.success) {
      action.textContent = showArtifactResult(
        documentNode, resultHost, artifact, response.envelope.result,
      ) || "";
      return;
    }
    // A failed read keeps the control live and says why: the reader has to
    // be able to try again, and a gate that silently shows nothing is the
    // chip-only state this module exists to end.
    resultHost.textContent =
      response.envelope?.error?.message || "Evidence unavailable.";
    open.disabled = false;
    action.disabled = false;
    action.textContent = "retry →";
    action.style.color = "var(--yoke-link)";
  };
  open.addEventListener("click", load);
  action.addEventListener("click", load);
  return card;
}

export const qaEvidenceArtifactView = {
  artifactCaption,
  artifactEvidenceCard,
  artifactHandle,
  artifactLabel,
  normalizeArtifact,
  showArtifactResult,
};

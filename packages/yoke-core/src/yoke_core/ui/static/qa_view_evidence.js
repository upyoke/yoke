import {
  callFunction,
  el,
  portabilityMode,
} from "./universe_view_support.js";
import { qaPanel } from "./qa_view_primitives.js";

function evidenceHandle(artifact) {
  if (!artifact.artifact_handle) return null;
  try {
    const handle = JSON.parse(artifact.artifact_handle);
    return handle && typeof handle === "object" ? handle : null;
  } catch {
    return null;
  }
}

function evidenceLabel(artifact) {
  const handle = evidenceHandle(artifact);
  if (!handle) return artifact.artifact_type;
  const key = handle.key ? String(handle.key).split("/").at(-1) : null;
  return handle.filename || key || handle.path || artifact.artifact_type;
}

function evidenceStorage(artifact, hostedLocal) {
  const handle = evidenceHandle(artifact);
  if (handle?.backend === "s3") {
    return "s3 handle · rendered via presigned read";
  }
  if (handle?.backend === "local") {
    return hostedLocal
      ? "local handle — on this machine only; viewable where it was " +
        "captured, not from this browser"
      : "local handle · available only from its capture machine";
  }
  return "typed artifact handle";
}

function showResult(documentNode, host, artifact, result) {
  host.replaceChildren();
  const disposition = result.disposition || "unavailable";
  if (disposition !== "ready") {
    const label = {
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
    return label;
  }
  if (typeof result.content_base64 === "string") {
    const source = `data:${result.content_type || "application/octet-stream"};base64,${result.content_base64}`;
    if (String(result.content_type || "").startsWith("image/")) {
      const image = el(documentNode, "img", "qa-evidence-preview");
      image.src = source;
      image.alt = evidenceLabel(artifact);
      host.appendChild(image);
    } else {
      const link = el(documentNode, "a", "qa-evidence-link", "open →");
      link.href = source;
      link.download = evidenceLabel(artifact);
      host.appendChild(link);
    }
    return null;
  }
  if (!result.download_url) {
    return "unavailable";
  }
  const link = el(documentNode, "a", "qa-evidence-link", "view →");
  link.href = result.download_url;
  link.target = "_blank";
  link.rel = "noopener";
  host.appendChild(link);
  return null;
}

function evidenceCard(context, artifact) {
  const documentNode = context.document;
  const hostedLocal = portabilityMode(context.capabilities) === "hosted"
    && evidenceHandle(artifact)?.backend === "local";
  const card = el(documentNode, "div", "qa-evidence");
  card.appendChild(el(documentNode, "span", "qa-evidence-icon", "🖼"));
  const copy = el(documentNode, "span");
  const open = el(
    documentNode,
    hostedLocal ? "span" : "button",
    hostedLocal ? "mono" : "qa-evidence-open",
    evidenceLabel(artifact),
  );
  if (!hostedLocal) open.type = "button";
  copy.appendChild(open);
  copy.appendChild(el(
    documentNode, "small", null,
    evidenceStorage(artifact, hostedLocal),
  ));
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
  action.setAttribute("aria-label", `View ${evidenceLabel(artifact)}`);
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
      const disposition = showResult(
        documentNode, resultHost, artifact, response.envelope.result,
      );
      action.textContent = disposition || "";
    } else {
      resultHost.textContent =
        response.envelope?.error?.message || "Evidence unavailable.";
      open.disabled = false;
      action.disabled = false;
      action.textContent = "retry →";
      action.style.color = "var(--yoke-link)";
    }
  };
  open.addEventListener("click", load);
  action.addEventListener("click", load);
  return card;
}

export function renderEvidence(context, plan) {
  const documentNode = context.document;
  const caseEvidence = plan.cases.map((row) => ({
    case_key: row.case_key,
    artifacts: (row.last_result.evidence || []).map((artifact) => ({
      ...artifact,
      case_key: row.case_key,
      requirement_id: row.last_result.requirement_id,
    })),
  })).filter((row) => row.artifacts.length);
  const artifacts = caseEvidence.flatMap((row) => row.artifacts);
  const title = caseEvidence.length === 1
    ? `Evidence · ${caseEvidence[0].case_key}`
    : caseEvidence.length > 1 ? "Evidence by case" : "Evidence";
  const result = qaPanel(
    documentNode,
    title,
    caseEvidence.length === 1 ? null : artifacts.length,
    "artifact read surface · both handle kinds",
  );
  if (!artifacts.length) {
    result.body.appendChild(el(
      documentNode, "p", "empty", "No case evidence captured yet.",
    ));
  }
  for (const row of caseEvidence) {
    if (caseEvidence.length > 1) {
      result.body.appendChild(el(
        documentNode, "h3", "qa-group-label mono", row.case_key,
      ));
    }
    for (const artifact of row.artifacts) {
      result.body.appendChild(evidenceCard(context, artifact));
    }
  }
  return result.root;
}

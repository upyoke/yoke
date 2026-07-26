import { callFunction, el } from "./universe_view_support.js";
import { qaPanel } from "./qa_view_primitives.js";

function evidenceLabel(artifact) {
  if (!artifact.artifact_handle) return artifact.artifact_type;
  try {
    const handle = JSON.parse(artifact.artifact_handle);
    const key = handle.key ? String(handle.key).split("/").at(-1) : null;
    return handle.filename || key || handle.path || artifact.artifact_type;
  } catch {
    return artifact.artifact_type;
  }
}

function showResult(documentNode, host, artifact, result) {
  host.replaceChildren();
  const disposition = result.disposition || "unavailable";
  if (disposition !== "ready") {
    const label = disposition === "evidence_on_machine"
      ? `Evidence on ${result.machine || "the capture machine"}`
      : disposition === "evidence_not_portable"
        ? "Evidence bytes were not portable"
        : result.detail || "Evidence unavailable";
    host.appendChild(el(documentNode, "span", "qa-evidence-state", label));
    return;
  }
  if (result.content_base64) {
    const source = `data:${result.content_type || "application/octet-stream"};base64,${result.content_base64}`;
    if (String(result.content_type || "").startsWith("image/")) {
      const image = el(documentNode, "img", "qa-evidence-preview");
      image.src = source;
      image.alt = evidenceLabel(artifact);
      host.appendChild(image);
    } else {
      const link = el(documentNode, "a", "qa-evidence-link", "Open evidence");
      link.href = source;
      link.download = evidenceLabel(artifact);
      host.appendChild(link);
    }
    return;
  }
  const link = el(documentNode, "a", "qa-evidence-link", "Open evidence");
  link.href = result.download_url;
  link.target = "_blank";
  link.rel = "noopener";
  host.appendChild(link);
}

function evidenceCard(context, artifact) {
  const documentNode = context.document;
  const card = el(documentNode, "div", "qa-evidence");
  card.appendChild(el(documentNode, "span", "qa-evidence-icon", "▧"));
  const copy = el(documentNode, "span");
  const open = el(
    documentNode, "button", "qa-evidence-open", evidenceLabel(artifact),
  );
  open.type = "button";
  copy.appendChild(open);
  copy.appendChild(el(
    documentNode, "small", null,
    `${artifact.case_key} · ${artifact.artifact_type}`,
  ));
  const resultHost = el(documentNode, "div", "qa-evidence-result");
  copy.appendChild(resultHost);
  card.appendChild(copy);
  open.addEventListener("click", async () => {
    open.disabled = true;
    resultHost.textContent = "loading evidence…";
    const response = await callFunction(
      context.client,
      "qa.artifact.read",
      { artifact_id: artifact.id },
      {
        kind: "qa_requirement",
        qa_requirement_id: artifact.requirement_id,
      },
    );
    if (response.status === 200 && response.envelope.success) {
      showResult(
        documentNode, resultHost, artifact, response.envelope.result,
      );
    } else {
      resultHost.textContent =
        response.envelope?.error?.message || "Evidence unavailable.";
      open.disabled = false;
    }
  });
  return card;
}

export function renderEvidence(context, plan) {
  const documentNode = context.document;
  const artifacts = plan.cases.flatMap((row) =>
    (row.last_result.evidence || []).map((artifact) => ({
      ...artifact,
      case_key: row.case_key,
      requirement_id: row.last_result.requirement_id,
    })));
  const result = qaPanel(documentNode, "Evidence", artifacts.length);
  if (!artifacts.length) {
    result.body.appendChild(el(
      documentNode, "p", "empty", "No case evidence captured yet.",
    ));
  }
  for (const artifact of artifacts) {
    result.body.appendChild(evidenceCard(context, artifact));
  }
  return result.root;
}

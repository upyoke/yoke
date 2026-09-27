import { callFunction, el } from "./universe_view_support.js";

export function failureOutputNode(documentNode, result) {
  const output = result.output_tail;
  if (result.outcome !== "failed" || typeof output !== "string" || !output) {
    return null;
  }
  const details = el(documentNode, "details", "qa-case-output");
  details.appendChild(el(documentNode, "summary", null, "failure output"));
  details.appendChild(el(documentNode, "pre", "qa-case-output-text", output));
  return details;
}

// A command check's evidence is the output it recorded, stored as a
// command_output artifact. Reading it here puts what the command printed on
// the case page instead of a card that only says an artifact exists.
export function isCommandOutput(artifact) {
  return String(artifact?.artifact_type || "") === "command_output";
}

function decodeText(base64) {
  const binary = atob(base64);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

// The recorded output, or null when its bytes are not portable to this
// reader (a machine-local handle, or a read that failed).
export async function readRecordedOutput(context, artifact) {
  try {
    const result = await callFunction(
      context.client, "qa.artifact.read", { artifact_id: Number(artifact.id) },
    );
    const content = result.status === 200 && result.envelope.success
      ? result.envelope.result?.content_base64 : null;
    return typeof content === "string" ? decodeText(content) : null;
  } catch {
    return null;
  }
}

export function recordedOutputNode(documentNode, text) {
  return el(documentNode, "pre", "qa-case-recorded-output", text.trimEnd());
}

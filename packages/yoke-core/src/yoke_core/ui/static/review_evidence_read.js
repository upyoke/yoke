// Reading one evidence artifact's bytes, and saying what came back.
//
// Every surface that draws evidence goes through here: a thumbnail, a text
// chip, a gate's evidence card. The read is shared and de-duplicated per
// view, because one artifact can appear in more than one place on a page and
// the bytes should be fetched once. The outcome is a plain verdict — ready
// with a source, or not ready with words a reader can act on — so a caller
// renders a state rather than interpreting an envelope.

import { callFunction } from "./universe_view_support.js";

const READ_TIMEOUT_MS = 15_000;

const UNAVAILABLE_STATES = {
  evidence_on_machine: (result) => `On ${result.machine || "its capture machine"}`,
  evidence_not_portable: () => "Not portable",
  too_large: () => "Too large to show",
  unavailable: () => "Image unavailable",
};

export function decodeText(base64) {
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function artifactReads(context) {
  if (!context.artifactReads) context.artifactReads = new Map();
  return context.artifactReads;
}

export async function readArtifact(context, artifact) {
  const reads = artifactReads(context);
  const key = `${artifact.requirement_id}:${artifact.id}`;
  const existing = reads.get(key);
  if (existing) return existing;
  let timer;
  const controller = typeof AbortController === "function"
    ? new AbortController() : null;
  const onAbort = () => controller?.abort();
  const signal = context.signal;
  if (signal?.aborted) onAbort();
  else signal?.addEventListener("abort", onAbort, { once: true });
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
    signal?.removeEventListener?.("abort", onAbort);
    // Delete only from this view's map. A route swap installs a new Map on
    // context before this finally runs, and must not lose the fresh read.
    if (reads.get(key) === pending) reads.delete(key);
  });
  reads.set(key, pending);
  return pending;
}

export function readOutcome(response) {
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

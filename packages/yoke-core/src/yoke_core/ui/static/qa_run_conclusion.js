// A CI check that captured no screenshot still proved a tree: the GitHub
// Actions run named on the row, at the SHA the run recorded. This draws
// that conclusion as something a reader can open. Capture-status rows with
// no artifacts stay on the "no artifacts" copy — they are not this shape.

import { el } from "./universe_view_support.js";

const ACTIONS_RUN = /^https:\/\/github(?:\.com|\.test)\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/actions\/runs\/\d+\/?$/;

export function runConclusionUrl(row) {
  const url = String(row?.run_url || "").trim();
  return ACTIONS_RUN.test(url) ? url.replace(/\/$/, "") : "";
}

export function isCiConclusion(row) {
  return Boolean(
    runConclusionUrl(row)
    || String(row?.ci_conclusion || "").trim()
    || String(row?.ci_run_id || "").trim(),
  );
}

function bindExternal(link, url) {
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

export function evidenceSummaryNode(documentNode, row, text, className) {
  const url = runConclusionUrl(row);
  const node = el(documentNode, url ? "a" : "div", className, text);
  return url ? bindExternal(node, url) : node;
}

export function appendRunConclusion(documentNode, host, row, className) {
  if (!isCiConclusion(row)) return null;
  const url = runConclusionUrl(row);
  const sha = String(row.recorded_head_sha || "").trim().slice(0, 12);
  if (url) {
    const link = bindExternal(
      el(documentNode, "a", className, "GitHub Actions run →"),
      url,
    );
    host.appendChild(link);
    return link;
  }
  host.appendChild(el(
    documentNode,
    "div",
    className,
    sha
      ? `Verdict rests on the run conclusion at revision ${sha}.`
      : "Verdict rests on the GitHub Actions run conclusion.",
  ));
  return host.lastChild;
}

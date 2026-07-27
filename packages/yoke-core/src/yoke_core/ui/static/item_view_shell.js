import { renderMarkdown } from "./markdown_view.js";
import { relativeTime } from "./universe_time.js";
import {
  el,
  statePill,
} from "./universe_view_support.js";
import { workflowPanel } from "./workflow_view_primitives.js";

export function actionLink(documentNode, text, href, primary = false) {
  const link = el(
    documentNode,
    "a",
    `item-action${primary ? " primary" : ""}`,
    text,
  );
  link.href = href;
  return link;
}

export function itemHeading(documentNode, item) {
  const block = el(documentNode, "div", "item-detail-heading-block");
  const header = el(
    documentNode, "div", "page-head item-detail-heading",
  );
  const copy = el(documentNode, "div", "h item-detail-heading-copy");
  copy.appendChild(el(documentNode, "h1", "title", item.title));
  header.appendChild(copy);
  block.appendChild(header);
  const state = el(documentNode, "div", "item-detail-state");
  const pill = statePill(
    documentNode,
    item.status,
    item.workflow.stage_label || item.status,
  );
  if (pill) state.appendChild(pill);
  const claim = item.claim;
  if (claim) {
    const claimFact = el(documentNode, "span", "item-muted");
    const actor = claim.actor_label || claim.session_id;
    claimFact.appendChild(el(documentNode, "span", null, `claimed by ${actor}`));
    if (
      String(item.workflow.id || "").toLowerCase() === "blitz" &&
      claim.session_id &&
      claim.session_id !== actor
    ) {
      claimFact.appendChild(el(documentNode, "span", null, " · "));
      claimFact.appendChild(el(
        documentNode,
        "span",
        "mono",
        claim.session_id,
      ));
    } else if (claim.claimed_at) {
      claimFact.appendChild(el(documentNode, "span", null, " · "));
      claimFact.appendChild(relativeTime(documentNode, claim.claimed_at));
    }
    state.appendChild(claimFact);
  } else if (item.owner) {
    state.appendChild(el(
      documentNode,
      "span",
      "item-muted",
      `owned by ${item.owner}`,
    ));
  }
  block.appendChild(state);
  return block;
}

export function textPanel(
  documentNode,
  title,
  text,
  emptyText = "None yet.",
  options = {},
) {
  const { panel, body } = workflowPanel(documentNode, title, {
    detail: options.detail,
  });
  const clean = String(text || "").trim();
  body.appendChild(renderMarkdown(documentNode, clean, {
    className: "rich-text item-prose",
    emptyText,
    omitLeadingHeading: options.omitLeadingHeading || [],
    demoteHeadings: true,
  }));
  return panel;
}

export function commandPanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Run in a harness");
  const copy = item.workflow.id === "issue"
    ? "The review loop runs in the claiming session; next after the gate:"
    : item.workflow.id === "epic"
      ? "Next — execute the planned tasks:"
      : "From your yoke-installed project repo:";
  body.appendChild(el(
    documentNode,
    "p",
    "item-muted item-command-copy",
    copy,
  ));
  const executor = item.workflow.next_executor_id ||
    item.workflow.executor_id ||
    item.workflow.id;
  body.appendChild(el(
    documentNode,
    "code",
    "item-command",
    `/yoke ${executor} ${item.public_ref}`,
  ));
  return panel;
}

export function progressPanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Progress Log");
  const content = String(item.progress_log?.content || "").trim();
  if (!content) {
    body.appendChild(el(
      documentNode, "p", "empty", "No progress entries yet.",
    ));
    return panel;
  }
  const marker = /^##\s+(.+?)\s+entry\s+—\s+(.+?)\s*$/gm;
  const matches = [...content.matchAll(marker)];
  if (!matches.length) {
    body.appendChild(renderMarkdown(documentNode, content, {
      className: "rich-text item-prose",
      demoteHeadings: true,
    }));
    return panel;
  }
  body.className += " item-progress";
  for (const [index, match] of matches.entries()) {
    const entry = el(documentNode, "article", "item-progress-entry");
    const heading = el(documentNode, "div", "item-progress-heading");
    const timestamp = match[1];
    if (Number.isNaN(new Date(timestamp).getTime())) {
      heading.appendChild(el(documentNode, "span", "item-muted", timestamp));
    } else {
      heading.appendChild(relativeTime(documentNode, timestamp));
    }
    entry.appendChild(heading);
    const start = Number(match.index) + match[0].length;
    const end = index + 1 < matches.length
      ? Number(matches[index + 1].index)
      : content.length;
    entry.appendChild(renderMarkdown(
      documentNode,
      content.slice(start, end).trim(),
      {
        className: "rich-text item-progress-body",
        emptyText: "No details recorded.",
        demoteHeadings: true,
      },
    ));
    body.appendChild(entry);
  }
  return panel;
}

export function detailColumns(documentNode, left, right) {
  const grid = el(documentNode, "div", "item-detail-grid");
  const leftColumn = el(documentNode, "div", "item-stack");
  for (const child of left) leftColumn.appendChild(child);
  const rightColumn = el(documentNode, "div", "item-stack");
  for (const child of right) rightColumn.appendChild(child);
  grid.appendChild(leftColumn);
  grid.appendChild(rightColumn);
  return grid;
}

export function markdownSection(text, heading) {
  const lines = String(text || "").split(/\r?\n/);
  const target = String(heading).toLowerCase();
  let collecting = false;
  let sectionLevel = null;
  const output = [];
  for (const line of lines) {
    const match = line.match(/^(#{2,6})\s+(.+?)\s*$/);
    if (match) {
      const level = match[1].length;
      const title = match[2].trim().toLowerCase();
      if (collecting && level <= sectionLevel) break;
      if (!collecting && title === target) {
        collecting = true;
        sectionLevel = level;
        continue;
      }
    }
    if (collecting) output.push(line);
  }
  return output.join("\n").trim();
}

export function withoutMarkdownSections(text, headings) {
  const omitted = new Set(headings.map((heading) => heading.toLowerCase()));
  const lines = String(text || "").split(/\r?\n/);
  const output = [];
  let skipping = false;
  let skipLevel = null;
  for (const line of lines) {
    const match = line.match(/^(#{2,6})\s+(.+?)\s*$/);
    if (match) {
      const level = match[1].length;
      const title = match[2].trim().toLowerCase();
      if (!skipping || level <= skipLevel) {
        skipping = omitted.has(title);
        skipLevel = skipping ? level : null;
      }
    }
    if (!skipping) output.push(line);
  }
  return output.join("\n").trim();
}

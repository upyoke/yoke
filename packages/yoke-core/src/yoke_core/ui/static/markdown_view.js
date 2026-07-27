import { el } from "./universe_view_support.js";

function appendText(documentNode, host, value) {
  if (!value) return;
  host.appendChild(el(documentNode, "span", null, value));
}

function safeHref(value) {
  const href = String(value || "").trim();
  return /^(?:https?:|mailto:|#|\/)/i.test(href) ? href : null;
}

function appendInline(documentNode, host, value) {
  const text = String(value || "");
  const token = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^)]+\)|\*[^*\n]+\*)/g;
  let cursor = 0;
  for (const match of text.matchAll(token)) {
    appendText(documentNode, host, text.slice(cursor, match.index));
    const raw = match[0];
    if (raw.startsWith("**")) {
      const strong = el(documentNode, "strong");
      appendInline(documentNode, strong, raw.slice(2, -2));
      host.appendChild(strong);
    } else if (raw.startsWith("`")) {
      host.appendChild(el(documentNode, "code", null, raw.slice(1, -1)));
    } else if (raw.startsWith("[")) {
      const parts = raw.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const href = parts && safeHref(parts[2]);
      if (parts && href) {
        const link = el(documentNode, "a", null, parts[1]);
        link.href = href;
        host.appendChild(link);
      } else {
        appendText(documentNode, host, raw);
      }
    } else {
      const emphasis = el(documentNode, "em");
      appendInline(documentNode, emphasis, raw.slice(1, -1));
      host.appendChild(emphasis);
    }
    cursor = Number(match.index) + raw.length;
  }
  appendText(documentNode, host, text.slice(cursor));
}

function appendParagraph(documentNode, host, lines) {
  const text = lines.join(" ").trim();
  if (!text) return;
  const paragraph = el(documentNode, "p");
  appendInline(documentNode, paragraph, text);
  host.appendChild(paragraph);
}

function normalizedHeading(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[`*_]/g, "")
    .replace(/\s+/g, " ");
}

function omittedLeadingHeading(line, candidates) {
  const match = line.match(/^#\s+(.+?)\s*$/);
  if (!match) return false;
  const heading = normalizedHeading(match[1]);
  return candidates.some((candidate) => normalizedHeading(candidate) === heading);
}

export function renderMarkdown(
  documentNode,
  content,
  {
    className = "rich-text",
    emptyText = "No content yet.",
    omitLeadingHeading = [],
    demoteHeadings = false,
  } = {},
) {
  const host = el(documentNode, "article", className);
  const source = String(content || "").replace(/<!--[\s\S]*?-->/g, "");
  const lines = source.split(/\r?\n/);
  const omitted = Array.isArray(omitLeadingHeading)
    ? omitLeadingHeading : [omitLeadingHeading];
  const firstContent = lines.findIndex((line) => line.trim());
  if (
    firstContent >= 0 &&
    omitted.length &&
    omittedLeadingHeading(lines[firstContent].trim(), omitted)
  ) {
    lines.splice(firstContent, 1);
  }

  let paragraph = [];
  let list = null;
  let listTag = null;
  let checklist = null;
  let code = null;

  const flushParagraph = () => {
    appendParagraph(documentNode, host, paragraph);
    paragraph = [];
  };
  const closeCollections = () => {
    list = null;
    listTag = null;
    checklist = null;
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (code) {
      if (/^```/.test(line)) {
        code = null;
      } else {
        code.textContent += `${code.textContent ? "\n" : ""}${raw}`;
      }
      continue;
    }
    if (/^```/.test(line)) {
      flushParagraph();
      closeCollections();
      const pre = el(documentNode, "pre", "rich-code-block");
      code = el(documentNode, "code");
      pre.appendChild(code);
      host.appendChild(pre);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+?)\s*$/);
    const check = line.match(/^[-*]\s+\[([ xX])\]\s+(.+)$/);
    const bullet = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeCollections();
      const rawLevel = heading[1].length + (demoteHeadings ? 1 : 0);
      const level = Math.max(2, Math.min(rawLevel, 6));
      const node = el(documentNode, `h${level}`);
      appendInline(documentNode, node, heading[2]);
      host.appendChild(node);
    } else if (check) {
      flushParagraph();
      list = null;
      listTag = null;
      if (!checklist) {
        checklist = el(documentNode, "div", "rich-checklist");
        host.appendChild(checklist);
      }
      const row = el(
        documentNode,
        "div",
        `rich-check${check[1].trim() ? " complete" : ""}`,
      );
      row.appendChild(el(
        documentNode,
        "span",
        "rich-check-glyph",
        check[1].trim() ? "☑" : "☐",
      ));
      const copy = el(documentNode, "span");
      appendInline(documentNode, copy, check[2]);
      row.appendChild(copy);
      checklist.appendChild(row);
    } else if (bullet || ordered) {
      flushParagraph();
      checklist = null;
      const nextTag = ordered ? "ol" : "ul";
      if (!list || listTag !== nextTag) {
        listTag = nextTag;
        list = el(documentNode, nextTag);
        host.appendChild(list);
      }
      const item = el(documentNode, "li");
      appendInline(documentNode, item, (ordered || bullet)[1]);
      list.appendChild(item);
    } else if (!line) {
      flushParagraph();
      closeCollections();
    } else {
      closeCollections();
      paragraph.push(line);
    }
  }
  flushParagraph();
  if (!host.children.length) {
    host.appendChild(el(documentNode, "p", "empty", emptyText));
  }
  return host;
}

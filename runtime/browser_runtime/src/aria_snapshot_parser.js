'use strict';

function mappingColon(entry) {
  let quoted = false;
  let escaped = false;
  let bracketDepth = 0;
  for (let index = 0; index < entry.length; index++) {
    const char = entry[index];
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === '"') quoted = false;
      continue;
    }
    if (char === '"') quoted = true;
    else if (char === '[') bracketDepth++;
    else if (char === ']') bracketDepth = Math.max(0, bracketDepth - 1);
    else if (char === ':' && bracketDepth === 0) return index;
  }
  return -1;
}

function yamlScalar(value) {
  const text = value.trim();
  if (text.startsWith('"') && text.endsWith('"')) {
    try {
      return JSON.parse(text);
    } catch {
      return text.slice(1, -1);
    }
  }
  if (text.startsWith("'") && text.endsWith("'")) {
    return text.slice(1, -1).replaceAll("''", "'");
  }
  return text;
}

function ariaNode(entry) {
  const roleMatch = entry.match(/^([a-z][a-z0-9-]*)/i);
  if (!roleMatch) {
    throw new Error(`invalid Playwright ARIA snapshot node: ${entry}`);
  }
  const node = { role: roleMatch[1], name: '' };
  let remainder = entry.slice(roleMatch[0].length).trim();
  if (remainder.startsWith('"')) {
    let escaped = false;
    let closingQuote = -1;
    for (let index = 1; index < remainder.length; index++) {
      const char = remainder[index];
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === '"') {
        closingQuote = index;
        break;
      }
    }
    if (closingQuote < 0) {
      throw new Error(`unterminated accessible name: ${entry}`);
    }
    node.name = yamlScalar(remainder.slice(0, closingQuote + 1));
    remainder = remainder.slice(closingQuote + 1).trim();
  }

  for (const match of remainder.matchAll(/\[([a-z]+)(?:=([^\]]+))?\]/gi)) {
    const key = match[1];
    const raw = match[2];
    if (raw === undefined || raw === 'true') node[key] = true;
    else if (raw === 'false') node[key] = false;
    else if (/^-?\d+(?:\.\d+)?$/.test(raw)) node[key] = Number(raw);
    else node[key] = raw;
  }
  return node;
}

/**
 * Convert Playwright ARIA snapshot YAML into the browser runtime's JSON tree.
 */
function parseAriaSnapshot(snapshot) {
  const root = { role: 'fragment', name: '', children: [] };
  const stack = [{ indent: -1, node: root }];

  for (const rawLine of String(snapshot || '').split(/\r?\n/)) {
    if (!rawLine.trim()) continue;
    const match = rawLine.match(/^(\s*)-\s+(.+)$/);
    if (!match) {
      throw new Error(`invalid Playwright ARIA snapshot line: ${rawLine}`);
    }
    const indent = match[1].length;
    const entry = match[2];
    while (stack.length > 1 && stack[stack.length - 1].indent >= indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].node;
    const colon = mappingColon(entry);
    const key = (colon < 0 ? entry : entry.slice(0, colon)).trim();
    const scalar = colon < 0 ? '' : entry.slice(colon + 1).trim();

    if (key.startsWith('/')) {
      parent[key.slice(1)] = yamlScalar(scalar);
      continue;
    }
    if (key === 'text') {
      parent.children = parent.children || [];
      parent.children.push({ role: 'StaticText', name: yamlScalar(scalar) });
      continue;
    }

    const node = ariaNode(key);
    parent.children = parent.children || [];
    parent.children.push(node);
    if (scalar) {
      node.children = [{
        role: 'StaticText',
        name: yamlScalar(scalar),
      }];
    }
    stack.push({ indent, node });
  }

  return root.children;
}

module.exports = { parseAriaSnapshot };

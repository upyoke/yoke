'use strict';

/**
 * Navigation/cursor action handlers: navigate, scroll, hover.
 *
 * Each handler takes (page, step, options[, refMap]) and returns
 * { success: boolean, artifacts?: string[] } or throws an Error.
 */

const { resolveTarget } = require('./target-helpers');

// Default timeout for scenario navigation actions.
const DEFAULT_TIMEOUT_MS = 5000;

// Query parameters whose value authenticates the request rather than
// describing it. A base URL carrying one is how a token-gated server
// recognises the session, so the value reaches every resolved route -- and
// must never reach an error message, a step result, or a run record, all of
// which are read by people who are not entitled to the credential.
const CREDENTIAL_QUERY_KEYS = new Set([
  'access_token',
  'api_key',
  'apikey',
  'auth',
  'authorization',
  'code',
  'id_token',
  'key',
  'passwd',
  'password',
  'pwd',
  'refresh_token',
  'secret',
  'session',
  'sig',
  'signature',
  'token',
]);

// Stands in for a credential value so the shape of the URL still reads.
const REDACTED_VALUE = 'REDACTED';

/**
 * Render *value* with every credential-bearing query value masked.
 *
 * Used wherever a URL is quoted back to a human or stored as evidence. A URL
 * that cannot be parsed is returned unchanged rather than suppressed: it
 * carries no query to leak, and hiding it would hide the diagnosis.
 *
 * @param {string} value
 * @returns {string}
 */
function redactUrl(value) {
  const text = String(value == null ? '' : value);
  let parsed;
  try {
    parsed = new URL(text);
  } catch (_) {
    return text;
  }
  for (const key of Array.from(parsed.searchParams.keys())) {
    if (CREDENTIAL_QUERY_KEYS.has(key.toLowerCase())) {
      parsed.searchParams.set(key, REDACTED_VALUE);
    }
  }
  return parsed.toString();
}

/**
 * Resolve a route against a base URL.
 *
 * Absolute routes pass through. Everything else resolves *under* the base
 * path with the WHATWG URL parser, which is what makes three shapes work
 * that string concatenation gets wrong:
 *
 *   - a fragment-only route (`#/route`) replaces only the fragment, instead
 *     of being appended after the query as `?token=X/#/route`;
 *   - a base carrying a path prefix (a universe served under `/yoke`) keeps
 *     that prefix, because the route resolves against the base directory
 *     rather than against the origin;
 *   - the base query survives, so a token-gated server still recognises the
 *     session on every route that did not state that parameter itself.
 *
 * @param {string} route
 * @param {string} baseUrl
 * @returns {string}
 */
function resolveUrl(route, baseUrl) {
  if (!route) return baseUrl;
  // Absolute URLs pass through
  if (/^https?:\/\//i.test(route)) return route;

  let base;
  try {
    base = new URL(baseUrl);
  } catch (_) {
    throw new Error(
      `options.baseUrl ${JSON.stringify(String(baseUrl))} is not an absolute `
      + 'URL, so route ' + JSON.stringify(String(route)) + ' cannot be '
      + 'resolved against it. Pass a base URL including its scheme, such as '
      + 'http://localhost:3000.'
    );
  }

  // Resolve against the base *directory* so a path-prefixed base survives,
  // and drop the route's leading slashes so `/route` and `route` mean the
  // same place under that prefix. Stripping them also means a
  // protocol-relative `//host/path` stays on the base origin.
  const directory = base.pathname.endsWith('/')
    ? base.pathname
    : `${base.pathname}/`;
  const resolved = new URL(
    route.replace(/^\/+/, ''),
    `${base.origin}${directory}`
  );

  // The route's own parameters win; the base contributes the rest.
  for (const [key, value] of base.searchParams) {
    if (!resolved.searchParams.has(key)) {
      resolved.searchParams.append(key, value);
    }
  }
  return resolved.toString();
}

// Statuses that mean the server declined to show the page at all. A
// navigation landing here has not arrived anywhere a later step can
// read, click or photograph -- the body is a refusal, and a screenshot
// of a refusal looks like a rendered page.
const AUTH_REFUSAL_STATUSES = new Set([401, 403]);

/**
 * Execute a navigate action.
 */
async function executeNavigate(page, step, options) {
  const url = resolveUrl(step.route, options.baseUrl);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  const response = await page.goto(url, { timeout, waitUntil: 'domcontentloaded' });
  const status = response ? response.status() : 0;
  if (AUTH_REFUSAL_STATUSES.has(status)) {
    throw new Error(
      `navigation to ${redactUrl(response.url())} was refused with HTTP ${status}: ` +
      'this page is an authentication refusal, not the screen the scenario ' +
      'asked for, and every following step would run against it. ' +
      'Establish the session first -- for a token-gated server, take one ' +
      '`snapshot screenshot` against the tokened URL on this same daemon ' +
      'and profile, then drive the remaining steps against bare paths.'
    );
  }
  return { success: true };
}

/**
 * Execute a scroll action.
 */
async function executeScroll(page, step, options, refMap) {
  if (step.target) {
    const locator = resolveTarget(page, step.target, refMap);
    const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
    await locator.scrollIntoViewIfNeeded({ timeout });
  } else {
    // Scroll the page by the specified amount or to bottom
    const x = step.x || 0;
    const y = step.y || 300;
    await page.mouse.wheel(x, y);
  }
  return { success: true };
}

/**
 * Execute a hover action.
 */
async function executeHover(page, step, options, refMap) {
  const locator = resolveTarget(page, step.target, refMap);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  await locator.hover({ timeout });
  return { success: true };
}

module.exports = {
  redactUrl,
  resolveUrl,
  executeNavigate,
  executeScroll,
  executeHover,
};

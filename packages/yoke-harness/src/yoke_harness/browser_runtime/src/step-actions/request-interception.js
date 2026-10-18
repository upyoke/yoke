'use strict';

// Rules belong to the exact page, including across separate CLI step calls.
// No request bodies, headers or cookies are retained in evidence.
const pages = new WeakMap();

function report(functionId, rule) {
  return { function_id: functionId, mode: rule.mode, matched: rule.matched,
    pending: rule.pending.size, rejected: rule.rejected, released: rule.released };
}

async function settle(rule, mode) {
  const pending = [...rule.pending];
  rule.pending.clear();
  for (const entry of pending) entry.resume(mode);
  await Promise.all(pending.map(entry => entry.done));
}

function pageRules(page) {
  let rules = pages.get(page);
  if (!rules) {
    rules = new Map();
    pages.set(page, rules);
    page.once('close', () => {
      for (const rule of rules.values()) {
        // Page closure aborts network traffic itself; unblock every callback.
        for (const entry of rule.pending) entry.resume('closed');
        rule.pending.clear();
      }
      rules.clear();
      pages.delete(page);
    });
  }
  return rules;
}

async function executeRequestInterception(page, step, options) {
  const functionId = step.function_id;
  const mode = step.mode;
  let origin;
  try {
    const url = new URL(options.baseUrl);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('not HTTP');
    origin = url.origin;
  } catch (_) {
    throw new Error('browser_interception_origin_required: use an http or https base URL.');
  }
  const rules = pageRules(page);
  let rule = rules.get(functionId);
  if (rule && rule.origin !== origin) {
    throw new Error('browser_interception_origin_mismatch: release the rule using its original base URL first.');
  }
  if (mode === 'status' || mode === 'release') {
    if (!rule) {
      throw new Error('browser_interception_missing: install hold or reject for this function_id on this page first.');
    }
    if (mode === 'release') {
      rule.mode = 'release';
      await page.unroute('**/*', rule.handler);
      await settle(rule, 'release');
      rules.delete(functionId);
    }
    return { interception: report(functionId, rule) };
  }
  if (rule) {
    rule.mode = mode;
    if (mode === 'reject') await settle(rule, 'reject');
    return { interception: report(functionId, rule) };
  }
  rule = { mode, origin, matched: 0, rejected: 0, released: 0, pending: new Set() };
  rule.handler = async route => {
    const request = route.request();
    let matches = false;
    try {
      matches = request.method() === 'POST'
        && new URL(request.url()).origin === origin
        && request.postDataJSON()?.function === functionId;
    } catch (_) { /* A non-JSON request is unrelated. */ }
    if (!matches) return route.fallback();
    rule.matched++;
    let decision = rule.mode;
    let finish;
    if (decision === 'hold') {
      const entry = {};
      entry.done = new Promise(resolve => { finish = resolve; });
      decision = await new Promise(resolve => {
        entry.resume = resolve;
        rule.pending.add(entry);
      });
      rule.pending.delete(entry);
    }
    try {
      if (decision === 'closed') return;
      if (decision === 'reject') {
        await route.abort('failed');
        rule.rejected++;
      } else {
        await route.fallback();
        rule.released++;
      }
    } finally {
      if (finish) finish();
    }
  };
  await page.route('**/*', rule.handler);
  rules.set(functionId, rule);
  return { interception: report(functionId, rule) };
}

module.exports = { executeRequestInterception };

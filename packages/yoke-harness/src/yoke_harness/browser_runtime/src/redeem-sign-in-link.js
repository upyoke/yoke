'use strict';

const refusals = new Set([
  'browser_sign_in_expired',
  'browser_sign_in_used',
  'browser_sign_in_oidc_required',
]);

async function redeemSignInLink(context, link) {
  try {
    const url = new URL(link);
    const code = url.hash.slice(1);
    url.hash = '';
    // The profile's request context shares its cookie jar with Chromium. The
    // link never becomes a page URL and the code never follows a redirect.
    const response = await context.request.post(url.href, {
      data: { code },
      maxRedirects: 0,
      timeout: 15000,
    });
    try {
      const result = await response.json();
      if (response.ok() && result.success === true) return { state: 'submitted' };
      const reason = result.error?.code;
      return { state: refusals.has(reason) ? reason : 'failed' };
    } finally {
      await response.dispose();
    }
  } catch (_) {
    return { state: 'failed' };
  }
}

module.exports = { redeemSignInLink };

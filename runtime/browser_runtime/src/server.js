'use strict';

/**
 * Express HTTP server for the browser daemon.
 *
 * Exports: createServer(options) -> Express app
 *
 * All routes require Bearer token auth.
 * Response shape: { success: boolean, data?: any, error?: string }
 */

const express = require('express');

/**
 * @param {Object} options
 * @param {number} options.port
 * @param {string} options.token
 * @param {Object} options.browserManager
 * @param {string} options.stateFilePath
 * @param {number} options.idleTimeoutMs
 * @param {function} [options.onActivity] - Called on each authenticated request (resets idle timer)
 * @param {function} [options.onStop] - Called when POST /api/stop is invoked
 * @returns {express.Application}
 */
function createServer(options) {
  const { token, browserManager, onActivity, onStop } = options;
  const startTime = Date.now();

  const app = express();
  app.use(express.json());

  // Bearer token auth middleware for all /api/* routes
  app.use('/api', (req, res, next) => {
    const authHeader = req.headers.authorization;
    if (!authHeader || authHeader !== `Bearer ${token}`) {
      return res.status(401).json({ success: false, error: 'Unauthorized' });
    }
    // Signal activity for idle timer reset
    if (typeof onActivity === 'function') {
      onActivity();
    }
    next();
  });

  // POST /api/health
  app.post('/api/health', (_req, res) => {
    const uptimeMs = Date.now() - startTime;
    res.json({
      success: true,
      data: {
        health: 'healthy',
        uptime_ms: uptimeMs,
        browser_connected: browserManager.isConnected(),
      },
    });
  });

  // POST /api/stop
  app.post('/api/stop', async (_req, res) => {
    res.json({ success: true, data: { message: 'Shutting down' } });
    if (typeof onStop === 'function') {
      // Give response time to flush before shutdown
      setTimeout(() => onStop(), 100);
    }
  });

  return app;
}

module.exports = { createServer };

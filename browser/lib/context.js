"use strict";

const { ActorError } = require("./errors");

function makeContext(options) {
  const ctx = {
    backend: options.backend,
    session: options.session,
    options: options.options || {},
    sleep: options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms))),
    lastActionAt: 0,
    trace: [],
    warnings: [],
    records: [],
    log: options.log || (() => {}),
    // Compliance state is copied into every record, so a reader can tell
    // whether robots.txt was consulted for this run without reading the CLI
    // flags that produced it.
    compliance: {
      strict_robots: Boolean((options.options || {}).strictRobots),
      robots_checked: false,
      checks: [],
    },
  };
  ctx.capture = (fields) => {
    const record = options.makeRecord({
      ...fields,
      backend: ctx.backend.name,
      interaction_trace: ctx.trace.slice(),
      compliance: {
        ...ctx.compliance,
        robots_checked: ctx.compliance.checks.length > 0,
        checks: ctx.compliance.checks.slice(-20),
      },
    });
    ctx.records.push(record);
    return record;
  };
  ctx.warn = (message) => {
    ctx.warnings.push(message);
    ctx.log(`warning: ${message}`);
  };
  return ctx;
}

async function withBackend(backend, fn) {
  try {
    return await fn();
  } finally {
    if (backend && typeof backend.close === "function") await backend.close();
  }
}

function requireOption(ctx, key, message) {
  const value = ctx.options[key];
  if (!value) throw new ActorError("argument", message || `missing --${key}`);
  return value;
}

module.exports = { makeContext, withBackend, requireOption };

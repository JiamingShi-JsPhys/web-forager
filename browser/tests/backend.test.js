"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { BridgeBackend, UnavailableBackend, createBackend } = require("../lib/backend");

const FIXTURES = path.join(__dirname, "fixtures");
const FAKE = path.join(FIXTURES, "fake-bridge.js");
const LEGACY = path.join(FIXTURES, "legacy-bridge.js");

function bridgeFor(script) {
  return new BridgeBackend(`"${process.execPath}" "${script}"`, { timeout: 5000 });
}

test("a bridge that describes itself is trusted for what it declares", async () => {
  const backend = bridgeFor(FAKE);
  try {
    const caps = await backend.capabilities();
    assert.equal(caps.declared, true);
    assert.equal(caps.source, "declared");
    assert.equal(caps.observe, true);
    assert.equal(caps.loginState, true);
  } finally {
    await backend.close();
  }
});

test("a bridge without describe gets conservative capabilities", async () => {
  const backend = bridgeFor(LEGACY);
  try {
    const caps = await backend.capabilities();
    assert.equal(caps.declared, false);
    assert.equal(caps.source, "undeclared");
    assert.equal(caps.observe, false);
    assert.equal(caps.loginState, false);
    assert.ok(caps.reason, "the reason is reported instead of a silent false");
  } finally {
    await backend.close();
  }
});

test("a missing bridge reports every capability as false", () => {
  const saved = process.env.WEB_FORAGER_BRIDGE;
  delete process.env.WEB_FORAGER_BRIDGE;
  try {
    const backend = createBackend({});
    assert.ok(backend instanceof UnavailableBackend);
    const caps = backend.capabilities();
    assert.equal(backend.available, false);
    assert.equal(caps.observe, false);
    assert.equal(caps.declared, false);
    assert.equal(caps.source, "unavailable");
  } finally {
    if (saved !== undefined) process.env.WEB_FORAGER_BRIDGE = saved;
  }
});

test("capabilities are not invented after the bridge is closed", async () => {
  const backend = bridgeFor(LEGACY);
  await backend.close();
  const caps = await backend.capabilities();
  assert.equal(caps.declared, false);
  assert.equal(caps.observe, false);
});

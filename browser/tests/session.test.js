"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  loadSession,
  saveSession,
  hasCaptured,
  markCaptured,
  markVisited,
  pushChain,
  sessionPath,
} = require("../lib/session");

test("session round-trips through disk", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "web-forager-browser-session-"));
  const previous = process.env.WEB_FORAGER_BROWSER_HOME;
  process.env.WEB_FORAGER_BROWSER_HOME = home;
  try {
    const session = loadSession("alpha", { playbook: "bili-feed" });
    assert.equal(session.name, "alpha");
    markVisited(session, "https://www.bilibili.com/");
    markCaptured(session, { id: "BV1aa411c7mD", url: "https://www.bilibili.com/video/BV1aa411c7mD", title: "A" });
    pushChain(session, "BV1aa411c7mD");
    saveSession(session);

    const loaded = loadSession("alpha");
    assert.deepEqual(loaded.visited, ["https://www.bilibili.com/"]);
    assert.equal(loaded.captured.length, 1);
    assert.deepEqual(loaded.chain, ["BV1aa411c7mD"]);
    assert.equal(hasCaptured(loaded, "BV1aa411c7mD"), true);
    assert.equal(sessionPath("alpha").startsWith(home), true);
    assert.equal(fs.existsSync(sessionPath("alpha")), true);
  } finally {
    if (previous === undefined) delete process.env.WEB_FORAGER_BROWSER_HOME;
    else process.env.WEB_FORAGER_BROWSER_HOME = previous;
  }
});

test("captured items are de-duplicated", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "web-forager-browser-dedupe-"));
  const previous = process.env.WEB_FORAGER_BROWSER_HOME;
  process.env.WEB_FORAGER_BROWSER_HOME = home;
  try {
    const session = loadSession("beta");
    assert.equal(markCaptured(session, { id: "BV1" }), true);
    assert.equal(markCaptured(session, { id: "BV1" }), false);
    assert.equal(session.captured.length, 1);
  } finally {
    if (previous === undefined) delete process.env.WEB_FORAGER_BROWSER_HOME;
    else process.env.WEB_FORAGER_BROWSER_HOME = previous;
  }
});

test("invalid session names are rejected", () => {
  assert.throws(() => sessionPath("../escape"), /invalid session name/);
  assert.throws(() => sessionPath("bad name"), /invalid session name/);
});

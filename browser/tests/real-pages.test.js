"use strict";

// Regression tests over snapshots derived from live pages (see
// tests/tools/html-to-snapshot.py and the recorded_at field in each file).
// They do not prove the sites still look like this; they prove a change to a
// selector breaks a test instead of silently emptying a playbook. The live
// check itself is tests/live-smoke.js, which is opt-in.

const test = require("node:test");
const assert = require("node:assert/strict");

const home = require("./fixtures/snapshots/bilibili-home.json");
const video = require("./fixtures/snapshots/bilibili-video.json");
const snapshot = require("../lib/snapshot");

test("the feed fixture yields real video cards with titles", () => {
  const cards = snapshot.findVideoCards(home);
  assert.ok(cards.length >= 5, `expected several cards, got ${cards.length}`);
  for (const card of cards) {
    assert.match(card.bvid, /^BV[0-9A-Za-z]{10}$/);
    assert.equal(card.url, `https://www.bilibili.com/video/${card.bvid}`);
    assert.ok(card.title.length > 0);
    assert.equal(/^[\d.]+[万亿]?\s+[\d.]+[万亿]?\s+\d{1,2}:\d{2}/.test(card.title), false, card.title);
  }
});

test("the video fixture yields a title and a BV id", () => {
  const meta = snapshot.extractVideoMeta(video);
  assert.equal(meta.bvid, "BV1GJ411x7h7");
  assert.ok(meta.title.length > 3);
  assert.ok(snapshot.commentCandidates(video).length > 0);
});

test("both fixtures read as ordinary pages, not as walls or blanks", () => {
  for (const page of [home, video]) {
    assert.equal(snapshot.hasLoginWall(page), false);
    assert.equal(snapshot.hasBlockedPage(page), false);
    assert.equal(snapshot.isBlankPage(page), false);
    assert.equal(snapshot.diagnoseEmpty(page), "no-match");
  }
});

test("fixtures record where they came from", () => {
  for (const page of [home, video]) {
    assert.equal(page.recorded_at, "2026-11-07");
    assert.match(page.recorded_from, /^https:\/\//);
    assert.ok(page.nodes.length > 50);
  }
});

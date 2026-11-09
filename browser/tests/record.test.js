"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { makeRecord, normalizeRecord, recordToMarkdown, slugify } = require("../lib/record");

test("record carries the shared retrieval shape", () => {
  const record = makeRecord({
    playbook: "bili-video",
    url: "https://www.bilibili.com/video/BV1aa411c7mD",
    backend: "iab",
    metadata: { bvid: "BV1aa411c7mD", title: "示例视频" },
    markdown: "正文",
    tables: [{ name: "t", columns: ["a"], rows: [[1]] }],
    warnings: ["one warning"],
  });
  assert.equal(record.source, "web-forager-browser");
  assert.equal(record.mode, "browser");
  assert.equal(record.schema_version, "2");
  assert.deepEqual(Object.keys(record.metadata), ["bvid", "title"]);
  assert.ok(record.captured_at);
  assert.equal(record.interaction_trace.length, 0);
  assert.equal(record.compliance.robots_checked, false);
});

test("record markdown includes metadata, body and warnings", () => {
  const record = makeRecord({
    playbook: "bili-feed",
    url: "https://example.org",
    backend: "fake",
    metadata: { title: "标题", bvid: "BV1" },
    markdown: "内容",
    warnings: ["w"],
  });
  const text = recordToMarkdown(record);
  assert.match(text, /^# 标题/);
  assert.match(text, /- bvid: BV1/);
  assert.match(text, /## Capture/);
  assert.match(text, /- w/);
});

test("slugify produces safe file names", () => {
  assert.equal(slugify("Hello World / 测试"), "hello-world-测试");
  assert.equal(slugify("", "fallback"), "fallback");
});

test("normalizeRecord folds an HTTP and a browser record onto one core", () => {
  const http = normalizeRecord({
    url: "https://example.org/a",
    final_url: "https://example.org/a",
    fetched_at: "2026-11-07T10:00:00Z",
    title: "A",
    metadata: { title: "A" },
    markdown: "body",
    tables: [],
    warnings: [],
    status: 200,
    cached: false,
  });
  const browser = normalizeRecord(
    makeRecord({
      playbook: "bili-video",
      url: "https://www.bilibili.com/video/BV1aa411c7mD",
      backend: "iab",
      metadata: { title: "B" },
      markdown: "body",
    }),
  );

  for (const record of [http, browser]) {
    assert.equal(record.schema_version, "core-1");
    for (const key of ["source", "mode", "url", "title", "collected_at", "metadata", "markdown", "tables", "warnings", "extra"]) {
      assert.ok(key in record, key);
    }
  }
  assert.equal(http.mode, "http");
  assert.equal(http.title, "A");
  assert.equal(http.extra.status, 200);
  assert.equal(browser.mode, "browser");
  assert.equal(browser.title, "B");
  assert.equal(browser.extra.playbook, "bili-video");
  assert.ok(browser.collected_at);
});

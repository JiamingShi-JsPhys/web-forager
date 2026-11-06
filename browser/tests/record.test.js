"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { makeRecord, recordToMarkdown, slugify } = require("../lib/record");

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
  assert.equal(record.schema_version, "1");
  assert.deepEqual(Object.keys(record.metadata), ["bvid", "title"]);
  assert.ok(record.captured_at);
  assert.equal(record.interaction_trace.length, 0);
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

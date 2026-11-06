"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { contextFor, FakeBackend } = require("./helpers");
const zhihu = require("../playbooks/zhihu-dig");
const xhs = require("../playbooks/xhs-dig");
const danmaku = require("../playbooks/bili-danmaku");

const BV1 = "BV1aa411c7mD";

function questionPage() {
  return {
    url: "https://www.zhihu.com/question/123",
    title: "如何学习 Python",
    nodes: [
      { role: "heading", name: "如何学习 Python" },
      { role: "text", name: "从语法开始，再做小项目，最后读源码。" },
    ],
  };
}

test("zhihu-dig ranks result links and captures the best unseen page", async () => {
  const searchPage = {
    url: "https://www.zhihu.com/search?type=content&q=Python",
    title: "知乎搜索",
    nodes: [
      { role: "link", name: "无关问题", href: "https://www.zhihu.com/question/999", locator: "q2" },
      { role: "link", name: "如何学习 Python - 知乎", href: "https://www.zhihu.com/question/123", locator: "q1" },
    ],
  };
  const backend = new FakeBackend([searchPage, questionPage()]);
  const ctx = contextFor(backend, { query: "Python" });
  const result = await zhihu.run(ctx);

  assert.equal(result.summary.results, 2);
  assert.equal(result.summary.captured, 1);
  assert.equal(ctx.records.length, 2);
  assert.equal(ctx.records[1].metadata.title, "如何学习 Python");
  assert.ok(ctx.records[0].tables[0].rows[0][2].includes("/question/123"));
  assert.ok(backend.actions.some((action) => action.action === "goto" && action.url.includes("/question/123")));
});

test("zhihu-dig reports a login wall instead of an empty result", async () => {
  const wall = {
    url: "https://www.zhihu.com/search?type=content&q=Python",
    title: "知乎",
    nodes: [{ role: "text", name: "扫码登录后查看搜索结果" }],
  };
  const backend = new FakeBackend([wall]);
  const ctx = contextFor(backend, { query: "Python" });

  await assert.rejects(() => zhihu.run(ctx), (error) => {
    assert.equal(error.code, "login_required");
    assert.match(error.hint, /extension bridge/i);
    return true;
  });
});

test("xhs-dig uses /explore links and captures one note", async () => {
  const searchPage = {
    url: "https://www.xiaohongshu.com/search_result?keyword=city+walk",
    title: "小红书搜索",
    nodes: [
      { role: "link", name: "无关笔记", href: "https://www.xiaohongshu.com/explore/zzz999", locator: "n2" },
      { role: "link", name: "城市漫步路线", href: "https://www.xiaohongshu.com/explore/abc123", locator: "n1" },
    ],
  };
  const note = {
    url: "https://www.xiaohongshu.com/explore/abc123",
    title: "城市漫步路线",
    nodes: [
      { role: "heading", name: "城市漫步路线" },
      { role: "text", name: "沿着老城区走一下午，经过三座桥和两个市场。" },
    ],
  };
  const backend = new FakeBackend([searchPage, note]);
  const ctx = contextFor(backend, { query: "城市 漫步" });
  const result = await xhs.run(ctx);

  assert.equal(result.summary.notes, 2);
  assert.equal(result.summary.captured, 1);
  assert.ok(result.summary.opened.includes("/explore/abc123"));
});

test("bili-danmaku reads timestamped danmaku from the snapshot", async () => {
  const page = {
    url: `https://www.bilibili.com/video/${BV1}`,
    title: "测试视频",
    nodes: [
      { role: "heading", name: "测试视频" },
      { role: "text", name: "00:12 前方高能" },
      { role: "text", name: "01:03 这也太真实了" },
    ],
  };
  const backend = new FakeBackend([page]);
  const ctx = contextFor(backend, { url: page.url });
  const result = await danmaku.run(ctx);

  assert.equal(result.summary.danmaku, 2);
  assert.equal(result.summary.source, "dom");
  assert.equal(ctx.records[0].metadata.experimental, true);
  assert.equal(ctx.records[0].tables[0].rows[0][0], "00:12");
  assert.equal(backend.actions.some((action) => action.action === "observe"), false);
});

test("bili-danmaku falls back to bridge observation", async () => {
  const page = { url: `https://www.bilibili.com/video/${BV1}`, title: "测试视频", nodes: [{ role: "heading", name: "测试视频" }] };
  const backend = new FakeBackend([page]);
  backend.observed = { topic: "danmaku", entries: [{ time: "00:05", text: "来了来了" }] };
  const ctx = contextFor(backend, { url: page.url, observeMs: 1500 });
  const result = await danmaku.run(ctx);

  assert.equal(result.summary.source, "network");
  assert.equal(result.summary.danmaku, 1);
  assert.ok(backend.actions.some((action) => action.action === "observe" && action.ms === 1500));
});

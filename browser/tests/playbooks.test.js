"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { contextFor, FakeBackend } = require("./helpers");
const feed = require("../playbooks/bili-feed");
const video = require("../playbooks/bili-video");
const chain = require("../playbooks/bili-chain");
const search = require("../playbooks/search-dig");

const BV1 = "BV1aa411c7mD";
const BV2 = "BV1bb411c7mD";

function card(title, bvid, locator) {
  return {
    role: "link",
    name: title,
    href: `https://www.bilibili.com/video/${bvid}`,
    locator,
  };
}

test("bili-feed captures unseen cards across screens", async () => {
  const backend = new FakeBackend([
    { url: "https://www.bilibili.com/", title: "首页", nodes: [card("视频一", BV1, "a1")] },
    { url: "https://www.bilibili.com/", title: "首页", nodes: [card("视频二", BV2, "a2")] },
  ]);
  const ctx = contextFor(backend, { maxItems: 5, maxScreens: 2 });
  const result = await feed.run(ctx);

  assert.equal(result.summary.captured, 2);
  assert.equal(ctx.records.length, 2);
  assert.deepEqual(ctx.session.captured.map((item) => item.id), [BV1, BV2]);
  assert.equal(backend.actions.filter((action) => action.action === "scroll").length, 1);
});

test("bili-feed skips already captured cards", async () => {
  const backend = new FakeBackend([
    { url: "https://www.bilibili.com/", title: "首页", nodes: [card("视频一", BV1, "a1")] },
  ]);
  const ctx = contextFor(backend, { maxItems: 5, maxScreens: 1 });
  ctx.session.captured.push({ id: BV1, url: "", title: "视频一" });
  const result = await feed.run(ctx);

  assert.equal(result.summary.captured, 0);
  assert.equal(ctx.records.length, 0);
});

test("bili-video captures metadata and visible comments", async () => {
  const page = {
    url: `https://www.bilibili.com/video/${BV1}`,
    title: "测试视频",
    nodes: [
      { role: "heading", name: "测试视频" },
      { role: "text", name: "1.2万播放 300弹幕" },
    ],
  };
  const withComments = {
    ...page,
    nodes: [...page.nodes, { role: "text", name: "评论一" }, { role: "text", name: "评论二" }],
  };
  const backend = new FakeBackend([page, withComments]);
  const ctx = contextFor(backend, { commentScrolls: 1, url: `https://www.bilibili.com/video/${BV1}` });
  const result = await video.run(ctx);

  assert.equal(ctx.records.length, 1);
  assert.equal(result.summary.bvid, BV1);
  assert.equal(ctx.records[0].metadata.stats["播放"], "1.2万");
  assert.ok(ctx.records[0].markdown.includes("评论一"));
  assert.equal(ctx.session.captured.length, 1);
});

test("bili-chain follows the next-episode control", async () => {
  const first = {
    url: `https://www.bilibili.com/video/${BV1}`,
    title: "第一话",
    nodes: [{ role: "heading", name: "第一话" }],
  };
  const firstWithNext = {
    ...first,
    nodes: [...first.nodes, { role: "link", name: "下一话", locator: "next" }],
  };
  const second = {
    url: `https://www.bilibili.com/video/${BV2}`,
    title: "第二话",
    nodes: [{ role: "heading", name: "第二话" }],
  };
  const secondWithoutNext = { ...second, nodes: [...second.nodes] };
  const backend = new FakeBackend([first, firstWithNext, second, secondWithoutNext]);
  const ctx = contextFor(backend, {
    maxItems: 2,
    commentScrolls: 1,
    url: `https://www.bilibili.com/video/${BV1}`,
  });
  const result = await chain.run(ctx);

  assert.equal(result.summary.captured, 2);
  assert.deepEqual(ctx.session.chain, [BV1, BV2]);
  assert.equal(backend.actions.filter((action) => action.action === "click").length, 1);
});

test("search-dig ranks results and opens the best match", async () => {
  const results = {
    url: "https://search.bilibili.com/all?keyword=Python",
    title: "搜索",
    nodes: [card("无关视频", BV2, "r2"), card("Python 教程 入门", BV1, "r1")],
  };
  const opened = {
    url: `https://www.bilibili.com/video/${BV1}`,
    title: "Python 教程 入门",
    nodes: [{ role: "heading", name: "Python 教程 入门" }],
  };
  const backend = new FakeBackend([results, opened]);
  const ctx = contextFor(backend, { query: "Python 教程", commentScrolls: 0 });
  const result = await search.run(ctx);

  assert.equal(result.summary.opened, BV1);
  assert.ok(ctx.records.some((record) => record.markdown.includes("Python 教程 入门")));
  assert.ok(backend.actions.some((action) => action.action === "goto" && action.url.includes(BV1)));
});

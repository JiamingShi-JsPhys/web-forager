#!/usr/bin/env node
"use strict";

// A dependency-free stand-in for a browser bridge. It implements the same
// line-delimited JSON-RPC 2.0 protocol as bridges/playwright-bridge.js, with
// deterministic pages, so the CLI can be exercised end to end without Chrome.

const PAGES = {
  video: {
    title: "测试视频",
    nodes: [
      { role: "heading", name: "测试视频" },
      { role: "text", name: "1.2万播放 300弹幕" },
      { role: "text", name: "评论一" },
      { role: "text", name: "评论二" },
    ],
  },
  zhihuSearch: {
    title: "知乎搜索",
    nodes: [
      { role: "link", name: "如何学习 Python - 知乎", href: "https://www.zhihu.com/question/123", locator: "q1" },
      { role: "link", name: "无关问题", href: "https://www.zhihu.com/question/999", locator: "q2" },
    ],
  },
  zhihuQuestion: {
    title: "如何学习 Python - 知乎",
    nodes: [
      { role: "heading", name: "如何学习 Python" },
      { role: "text", name: "从语法开始，再做小项目，最后读源码。" },
    ],
  },
  xhsSearch: {
    title: "小红书搜索",
    nodes: [
      { role: "link", name: "城市漫步路线", href: "https://www.xiaohongshu.com/explore/abc123", locator: "n1" },
      { role: "link", name: "无关笔记", href: "https://www.xiaohongshu.com/explore/zzz999", locator: "n2" },
    ],
  },
  xhsNote: {
    title: "城市漫步路线",
    nodes: [
      { role: "heading", name: "城市漫步路线" },
      { role: "text", name: "沿着老城区走一下午，经过三座桥和两个市场。" },
    ],
  },
  blank: { title: "空白页", nodes: [] },
};

let current = "https://example.org/";
let title = "空白页";

function pageFor(url) {
  if (/\/video\/BV/.test(url)) return PAGES.video;
  if (/zhihu\.com\/search/.test(url)) return PAGES.zhihuSearch;
  if (/zhihu\.com\/question\//.test(url)) return PAGES.zhihuQuestion;
  if (/xiaohongshu\.com\/search_result/.test(url)) return PAGES.xhsSearch;
  if (/xiaohongshu\.com\/explore\//.test(url)) return PAGES.xhsNote;
  return PAGES.blank;
}

const METHODS = {
  async goto(params) {
    current = String(params.url || current);
    title = pageFor(current).title;
    return { url: current, title };
  },
  async snapshot() {
    const page = pageFor(current);
    return { url: current, title: page.title, nodes: page.nodes };
  },
  async click() {
    return { ok: true };
  },
  async scroll() {
    return { ok: true };
  },
  async screenshot() {
    return { path: "" };
  },
  async tabs() {
    return { tabs: [{ url: current, title }] };
  },
  async observe(params) {
    return { topic: params.topic || "danmaku", entries: [{ time: "00:12", text: "前方高能" }] };
  },
};

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let newline = buffer.indexOf("\n");
  while (newline >= 0) {
    const line = buffer.slice(0, newline).trim();
    buffer = buffer.slice(newline + 1);
    newline = buffer.indexOf("\n");
    if (!line) continue;
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      send({ jsonrpc: "2.0", id: null, error: { code: "protocol", message: "parse error" } });
      continue;
    }
    const handler = METHODS[message.method];
    if (!handler) {
      send({ jsonrpc: "2.0", id: message.id, error: { code: "protocol", message: "unknown method" } });
      continue;
    }
    Promise.resolve(handler(message.params || {}))
      .then((result) => send({ jsonrpc: "2.0", id: message.id, result }))
      .catch((error) => send({ jsonrpc: "2.0", id: message.id, error: { code: "navigation", message: error.message } }));
  }
});

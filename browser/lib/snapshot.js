"use strict";

const BV = /\/video\/(BV[0-9A-Za-z]+)/;

function textOf(node) {
  if (!node) return "";
  return [node.name, node.text, node.label, node.title].filter(Boolean).join(" ").trim();
}

function allText(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  return [snapshot && snapshot.title, ...nodes.map(textOf)].filter(Boolean).join("\n");
}

function bvidFrom(value) {
  const match = String(value || "").match(BV) || String(value || "").match(/\b(BV[0-9A-Za-z]{10})\b/);
  return match ? match[1] : "";
}

function findVideoCards(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const seen = new Set();
  const cards = [];
  for (const node of nodes) {
    const bvid = bvidFrom(node.href) || bvidFrom(textOf(node));
    if (!bvid || seen.has(bvid)) continue;
    seen.add(bvid);
    const title = (node.name || node.text || bvid).replace(/\s+/g, " ").trim().slice(0, 160);
    cards.push({
      bvid,
      title,
      url: `https://www.bilibili.com/video/${bvid}`,
      locator: node.locator || node.href || node.name || bvid,
    });
  }
  return cards;
}

function extractVideoMeta(snapshot) {
  const text = allText(snapshot);
  const url = (snapshot && snapshot.url) || "";
  const bvid = bvidFrom(url) || (findVideoCards(snapshot)[0] || {}).bvid || "";
  const heading = (snapshot && snapshot.nodes ? snapshot.nodes : []).find(
    (node) => /heading/i.test(node.role || "") && textOf(node).length > 2,
  );
  const title = (heading ? (heading.name || heading.text) : "") || (snapshot && snapshot.title) || bvid;
  const stats = {};
  const statPattern = /([\d.]+\s*[万亿]?)\s*(播放|弹幕|追番|点赞|评论)/g;
  let match;
  while ((match = statPattern.exec(text)) !== null) {
    stats[match[2]] = match[1].replace(/\s+/g, "");
  }
  return { bvid, title: title.trim(), url, stats };
}

function findNextEpisode(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  return (
    nodes.find((node) => /^(下一个|下一话|下一集|下一P|next)/i.test(textOf(node).trim())) || null
  );
}

function rankByQuery(cards, query) {
  const tokens = String(query || "")
    .toLowerCase()
    .split(/[\s,，、]+/)
    .filter((token) => token.length > 0);
  if (!tokens.length) return cards.slice();
  return cards
    .map((card) => {
      const title = card.title.toLowerCase();
      const score = tokens.reduce((sum, token) => sum + (title.includes(token) ? 1 : 0), 0);
      return { card, score };
    })
    .sort((left, right) => right.score - left.score)
    .map((entry) => entry.card);
}

function findLinks(snapshot, pattern) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const seen = new Set();
  const links = [];
  for (const node of nodes) {
    const href = String(node.href || "");
    if (!pattern.test(href) || seen.has(href)) continue;
    seen.add(href);
    const title = (node.name || node.text || href).replace(/\s+/g, " ").trim().slice(0, 160);
    links.push({ title, url: href, locator: node.locator || href || title });
  }
  return links;
}

function pageTitle(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const heading = nodes.find((node) => /heading/i.test(node.role || "") && (node.name || node.text));
  return ((heading && (heading.name || heading.text)) || (snapshot && snapshot.title) || "").trim();
}

function bodyText(snapshot, limit = 8000) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const nav = /^(首页|推荐|热榜|视频|直播|会员|登录|注册|搜索|关注|收藏|消息|通知|设置|下载|APP|反馈)$/;
  const parts = [];
  for (const node of nodes) {
    const text = textOf(node).replace(/\s+/g, " ").trim();
    if (text.length < 8 || nav.test(text)) continue;
    if (/^https?:\/\//.test(text)) continue;
    parts.push(text);
    if (parts.join("\n\n").length >= limit) break;
  }
  return parts.join("\n\n").slice(0, limit);
}

function hasLoginWall(snapshot) {
  const text = allText(snapshot);
  return /扫码登录|密码登录|登录后查看|登录后继续|请先登录|请登录后/.test(text);
}

function findDanmaku(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const entries = [];
  for (const node of nodes) {
    const text = textOf(node).replace(/\s+/g, " ").trim();
    const match = text.match(/^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$/);
    if (match) entries.push({ time: match[1], text: match[2].slice(0, 200) });
  }
  return entries;
}

function commentCandidates(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const seen = new Set();
  const comments = [];
  for (const node of nodes) {
    if (node.href) continue;
    const text = textOf(node).replace(/\s+/g, " ").trim();
    if (text.length < 2 || text.length > 500) continue;
    if (/^(首页|番剧|直播|游戏中心|会员购|漫画|赛事|下载客户端|登录|注册|投稿)$/.test(text)) continue;
    if (seen.has(text)) continue;
    seen.add(text);
    comments.push(text);
  }
  return comments.slice(0, 60);
}

module.exports = {
  bvidFrom,
  textOf,
  allText,
  findVideoCards,
  extractVideoMeta,
  findNextEpisode,
  rankByQuery,
  commentCandidates,
  findLinks,
  pageTitle,
  bodyText,
  hasLoginWall,
  findDanmaku,
};

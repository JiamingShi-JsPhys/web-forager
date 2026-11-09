"use strict";

// Every structural assumption about a third-party page lives here, so a site
// redesign is a one-file change. Each block names the page it was written
// against and the fixture under tests/fixtures/snapshots/ that keeps it
// regression-tested. These patterns are heuristics: a redesign can silently
// stop matching, which is why the playbooks report a degraded run instead of
// an empty success.

const BILIBILI = {
  // https://www.bilibili.com/ and /video/BV...
  videoPath: /\/video\/(BV[0-9A-Za-z]+)/,
  videoId: /\b(BV[0-9A-Za-z]{10})\b/,
  statLabels: /([\d.]+\s*[万亿]?)\s*(播放|弹幕|追番|点赞|评论)/g,
  navWords: /^(首页|推荐|热榜|视频|直播|会员|登录|注册|搜索|关注|收藏|消息|通知|设置|下载|APP|反馈)$/,
  chromeLines: /^(首页|番剧|直播|游戏中心|会员购|漫画|赛事|下载客户端|登录|注册|投稿)$/,
  nextEpisode: /^(下一个|下一话|下一集|下一P|next)/i,
  homeUrl: "https://www.bilibili.com/",
  searchUrl: "https://search.bilibili.com/all",
};

const ZHIHU = {
  // https://www.zhihu.com/search?type=content&q=...
  searchUrl: "https://www.zhihu.com/search?type=content&q=",
  resultLink: /\/(question|answer|p)\/\d+/,
};

const XIAOHONGSHU = {
  // https://www.xiaohongshu.com/search_result?keyword=...
  searchUrl: "https://www.xiaohongshu.com/search_result?keyword=",
  resultLink: /\/explore\/[0-9A-Za-z]+|\/discovery\/item\/[0-9A-Za-z]+/,
};

// Chinese login interstitials. Read as data: a match only means "the page is
// asking for credentials", never that we should try to supply them.
const LOGIN_WALL = /扫码登录|密码登录|登录后查看|登录后继续|请先登录|请登录后/;

// Anti-bot, rate-limit and error interstitials. Checked only when a playbook
// found nothing, so ordinary pages that merely mention these words are safe.
const BLOCKED = /人机验证|安全验证|访问过于频繁|请求过于频繁|操作过于频繁|请稍后重试|滑块验证|captcha|verify you are human|access denied|403 forbidden|404 not found/i;

// A page with less readable text than this is treated as blank: either the
// selector assumptions moved or the site returned a shell.
const MIN_BODY_CHARS = 40;

// Danmaku text layouts seen in DOM snapshots. The bridge may also hand back
// structured entries ({time, text}), which is preferred because it does not
// depend on how the player renders text.
const DANMAKU = {
  textPatterns: [
    /^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$/,
    /^[[(【]?(\d{1,2}:\d{2}(?::\d{2})?)[\])】]?\s*[-—:]?\s*(.+)$/,
  ],
  roles: /^(danmaku|danmu|弹幕)$/i,
};

module.exports = {
  BILIBILI,
  ZHIHU,
  XIAOHONGSHU,
  LOGIN_WALL,
  BLOCKED,
  MIN_BODY_CHARS,
  DANMAKU,
};

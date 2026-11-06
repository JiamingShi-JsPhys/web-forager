"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto } = require("../lib/safety");
const { findLinks, rankByQuery, hasLoginWall } = require("../lib/snapshot");
const { hasCaptured, markCaptured, markVisited } = require("../lib/session");
const { capturePage } = require("./shared");

const NAME = "xhs-dig";
const SEARCH = "https://www.xiaohongshu.com/search_result?keyword=";
const RESULT_LINK = /\/explore\/[0-9A-Za-z]+|\/discovery\/item\/[0-9A-Za-z]+/;

module.exports = {
  name: NAME,
  description: "Search Xiaohongshu public notes, rank note links by query overlap, and capture the best unseen note.",
  requires: ["query"],

  async run(ctx) {
    const query = ctx.options.query;
    if (!query) throw new ActorError("argument", "xhs-dig needs --query");

    const searchUrl = `${SEARCH}${encodeURIComponent(query)}`;
    await guardedGoto(ctx, searchUrl);
    markVisited(ctx.session, searchUrl);

    const snapshot = await ctx.backend.snapshot();
    const ranked = rankByQuery(findLinks(snapshot, RESULT_LINK), query);
    if (!ranked.length) {
      if (hasLoginWall(snapshot)) {
        throw new ActorError(
          "login_required",
          "Xiaohongshu showed a login wall before any note links",
          "Use a logged-in extension bridge, or open a public note URL directly with the page playbook.",
        );
      }
      ctx.warn("no note links found");
      return { summary: { query, notes: 0, captured: 0 } };
    }

    ctx.capture({
      playbook: NAME,
      url: searchUrl,
      metadata: { query, site: "xiaohongshu", notes: ranked.length },
      markdown: ranked
        .slice(0, 10)
        .map((item, index) => `${index + 1}. ${item.title} - ${item.url}`)
        .join("\n"),
      tables: [
        {
          name: "xiaohongshu notes",
          columns: ["#", "title", "url"],
          rows: ranked.slice(0, 20).map((item, index) => [index + 1, item.title, item.url]),
        },
      ],
    });

    const target = ranked.find((item) => !hasCaptured(ctx.session, item.url));
    if (!target) {
      ctx.warn("all notes already captured");
      return { summary: { query, notes: ranked.length, captured: 0 } };
    }

    await guardedGoto(ctx, target.url);
    markVisited(ctx.session, target.url);
    const page = await capturePage(ctx, { url: target.url, site: "xiaohongshu", playbook: NAME });
    markCaptured(ctx.session, { id: target.url, url: target.url, title: page.title, playbook: NAME });

    return { summary: { query, notes: ranked.length, captured: 1, opened: target.url, title: page.title } };
  },
};

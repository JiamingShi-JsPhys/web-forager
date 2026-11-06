"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto } = require("../lib/safety");
const { findVideoCards, rankByQuery } = require("../lib/snapshot");
const { hasCaptured, markCaptured, markVisited } = require("../lib/session");
const { openAndCapture } = require("./shared");

const NAME = "search-dig";

module.exports = {
  name: NAME,
  description: "Search Bilibili, rank the result cards by query overlap, and capture the best unseen result.",
  requires: ["query"],

  async run(ctx) {
    const query = ctx.options.query;
    if (!query) throw new ActorError("argument", "search-dig needs --query");

    const base = ctx.options.url || "https://search.bilibili.com/all";
    const searchUrl = `${base}?keyword=${encodeURIComponent(query)}`;
    await guardedGoto(ctx, searchUrl);
    markVisited(ctx.session, searchUrl);

    const snapshot = await ctx.backend.snapshot();
    const ranked = rankByQuery(findVideoCards(snapshot), query);
    if (!ranked.length) {
      return { summary: { query, results: 0, captured: 0 }, warnings: ["no result cards found"] };
    }

    ctx.capture({
      playbook: NAME,
      url: searchUrl,
      metadata: { query, results: ranked.length },
      markdown: ranked
        .slice(0, 10)
        .map((card, index) => `${index + 1}. ${card.title} - ${card.url}`)
        .join("\n"),
      tables: [
        {
          name: "search results",
          columns: ["#", "title", "bvid", "url"],
          rows: ranked.slice(0, 20).map((card, index) => [index + 1, card.title, card.bvid, card.url]),
        },
      ],
    });

    const target = ranked.find((card) => !hasCaptured(ctx.session, card.bvid));
    if (!target) {
      return { summary: { query, results: ranked.length, captured: 0 }, warnings: ["all results already captured"] };
    }

    const result = await openAndCapture(ctx, target.url, {
      commentScrolls: Number(ctx.options.commentScrolls === undefined ? 1 : ctx.options.commentScrolls),
      playbook: NAME,
    });
    markCaptured(ctx.session, {
      id: target.bvid,
      url: target.url,
      title: target.title,
      playbook: NAME,
    });

    return {
      summary: {
        query,
        results: ranked.length,
        captured: 1,
        opened: result.meta.bvid || target.bvid,
        title: result.meta.title || target.title,
      },
    };
  },
};

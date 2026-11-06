module.exports = {
  name: "web-forager",
  apply: function (ctx) {
    console.log("[web-forager] Plugin mounted via CJS; CLI and MCP entry points stay in the plugin directory.");
    return { status: "active" };
  }
};

module.exports = {
  name: "web-forager",
  apply: function (ctx) {
    console.log("[web-forager] Activated via CJS.");
    console.log("[web-forager] Entry point: python run.py --action fetch|clean|bili|surf|scholar|map");
    console.log("[web-forager] MCP server: python mcp_server.py (stdio JSON-RPC)");
    return { status: "active" };
  }
};

module.exports = {
  name: "web-forager",
  apply: function (ctx) {
    console.log("[web-forager] Activated via CJS.");
    console.log("[web-forager] Entry point: python run.py --action fetch|clean|bili|surf|scholar|map");
    console.log("[web-forager] MCP server: python mcp_server.py (stdio JSON-RPC)");
    console.log("[web-forager] Browser mode: node browser/run.js --playbook <name>");
    console.log("[web-forager] Browser MCP: node browser/mcp_server.js (stdio JSON-RPC)");
    return { status: "active" };
  }
};

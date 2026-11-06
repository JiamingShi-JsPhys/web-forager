module.exports = {
  name: "web-forager",
  apply: function (ctx) {
    console.log("[web-forager] Activated via CJS.");
    console.log("[web-forager] Entry point: python run.py --action fetch|clean|bili");
    return { status: "active" };
  }
};

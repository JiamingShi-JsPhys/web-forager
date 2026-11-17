import { readdir, rm } from "node:fs/promises";
import { join } from "node:path";

// npm packs the working tree, not the Git index. A local test run leaves
// __pycache__ inside scripts/ and browser/, and the compiled files contain
// absolute paths from this machine. Remove them before every pack/publish.
const SKIP = new Set([".git", "node_modules", ".venv"]);

async function clean(dir) {
  let removed = 0;
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__pycache__") {
        await rm(path, { recursive: true, force: true });
        removed += 1;
      } else {
        removed += await clean(path);
      }
    } else if (entry.isFile() && entry.name.endsWith(".pyc")) {
      await rm(path, { force: true });
      removed += 1;
    }
  }
  return removed;
}

const removed = await clean(process.cwd());
console.log(`clean-pycache: removed ${removed} item(s)`);

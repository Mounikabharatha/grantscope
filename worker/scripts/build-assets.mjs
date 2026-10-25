// Copies the search page and the grant PDFs into ./public for `wrangler deploy`.
// The page is shared with the local FastAPI app, so both always serve the same UI.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../..", import.meta.url).pathname;
const out = new URL("../public", import.meta.url).pathname;
rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "pdfs"), { recursive: true });

cpSync(join(root, "app/static/index.html"), join(out, "index.html"));
const raw = join(root, "data/raw");
const pdfs = existsSync(raw) ? readdirSync(raw).filter((f) => f.endsWith(".pdf")) : [];
for (const f of pdfs) cpSync(join(raw, f), join(out, "pdfs", f));
console.log(`public/: index.html + ${pdfs.length} PDFs`);

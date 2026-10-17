// Bashi launcher: reads one JSON message per line from Claude Desktop and forwards it
// to the live Bashi site. No database, no keys, no packages needed.
const readline = require("readline");

// Try the older internet address style first. Some home networks stall on the newer one.
try { require("dns").setDefaultResultOrder("ipv4first"); } catch {}

const URL_MCP = (process.env.BASHI_URL || "https://bashi-vrfv.onrender.com").replace(/\/+$/, "") + "/mcp";

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

async function forward(msg) {
  const isRequest = msg && typeof msg === "object" && "id" in msg;
  try {
    const res = await fetch(URL_MCP, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(msg),
      signal: AbortSignal.timeout(60000),
    });
    if (!isRequest) return;
    const text = await res.text();
    if (!text.trim()) throw new Error("Empty reply from Bashi (HTTP " + res.status + ")");
    send(JSON.parse(text));
  } catch (e) {
    process.stderr.write("Bashi launcher: " + e.message + "\n");
    if (isRequest) {
      send({ jsonrpc: "2.0", id: msg.id, error: { code: -32000, message: "Could not reach Bashi: " + e.message } });
    }
  }
}

const rl = readline.createInterface({ input: process.stdin });
const pending = new Set();
rl.on("line", (line) => {
  line = line.trim();
  if (!line) return;
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
    return;
  }
  const p = forward(msg).finally(() => pending.delete(p));
  pending.add(p);
});
rl.on("close", () => Promise.all(pending).then(() => process.exit(0)));
process.stderr.write("Bashi launcher ready, forwarding to " + URL_MCP + "\n");

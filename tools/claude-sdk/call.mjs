// dataforge ↔ Claude Agent SDK bridge.
//
// Reads JSON from stdin: {"prompt": "...", "system": "...", "model": "..."}
// Writes the generated text to stdout. Exits non-zero on error with a JSON
// error blob on stderr.
//
// Uses the OAuth-backed Claude Code session (Pro/Max subscription). All
// host-level tools, MCP servers, hooks, skills, and settings are disabled
// so this behaves as a pure text-completion endpoint.

import { query } from "@anthropic-ai/claude-agent-sdk";

async function readStdin() {
  let buf = "";
  for await (const chunk of process.stdin) buf += chunk;
  return buf;
}

async function main() {
  const raw = await readStdin();
  let req;
  try {
    req = JSON.parse(raw);
  } catch (e) {
    process.stderr.write(JSON.stringify({ error: "invalid JSON on stdin", detail: String(e) }));
    process.exit(2);
  }
  if (!req?.prompt) {
    process.stderr.write(JSON.stringify({ error: "missing 'prompt' field" }));
    process.exit(2);
  }
  const model = req.model || "claude-opus-4-7";
  const stream = query({
    prompt: req.prompt,
    options: {
      model,
      systemPrompt: req.system || undefined,
      cwd: "/tmp",
      maxTurns: 1,
      permissionMode: "bypassPermissions",
      allowedTools: [],
      tools: [],
      mcpServers: {},
      skills: [],
      hooks: {},
      agents: {},
      settingSources: [],
      includePartialMessages: false,
    },
  });
  let text = "";
  for await (const msg of stream) {
    if (msg.type === "assistant") {
      const content = msg.message?.content;
      if (Array.isArray(content)) {
        for (const block of content) {
          if (block.type === "text" && block.text) text += block.text;
        }
      }
    }
    if (msg.type === "result" && msg.is_error) {
      process.stderr.write(JSON.stringify({ error: "Claude SDK error", detail: msg.result || msg }));
      process.exit(3);
    }
  }
  process.stdout.write(text);
}

main().catch((e) => {
  process.stderr.write(JSON.stringify({ error: "exception", detail: String(e) }));
  process.exit(1);
});

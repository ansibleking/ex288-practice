import type { ChatContext, ChatTurn, McpTool } from "./types.js";
import { mcpCallTool } from "./mcpClient.js";

const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";
const MAX_TOOL_ROUNDS = 8;
const MAX_TOKENS = 4096;

function buildSystemPrompt(context: ChatContext): string {
  const base = [
    "You are a hardware operations assistant for a fleet of DMTF Redfish-managed",
    "servers (iDRAC, iLO, XCC, OpenBMC, etc), acting through MCP tools exposed by",
    "the mirastack-redfish-mcp server. Nearly every tool takes an optional",
    "'endpoint' argument naming which server in the fleet to target; omit it to",
    "hit the default endpoint. If the user asks about 'all servers' or 'the",
    "fleet', call the relevant tool once per configured endpoint and summarize",
    "across them rather than only checking the default one. Prefer read/",
    "diagnostic tools first. The server itself gate-keeps mutating actions",
    "behind an explicit write-mode and dry-run-first confirmation, so if a",
    "mutating tool call is rejected or comes back as a dry-run, explain that to",
    "the user rather than retrying blindly. Be concise, and summarize tool",
    "output instead of dumping raw JSON back at the user unless they ask for",
    "the raw data.",
  ].join(" ");

  if (context.endpoints.length === 0) {
    return base;
  }
  const list = context.endpoints
    .map((e) => `- ${e.name} (${e.base_url})${e.read_only ? " [read-only]" : ""}`)
    .join("\n");
  const active = context.activeEndpoint ? `\n\nCurrently selected in the GUI: ${context.activeEndpoint}.` : "";
  return `${base}\n\nConfigured fleet endpoints:\n${list}${active}`;
}

function toAnthropicTools(tools: McpTool[]) {
  return tools.map((tool) => ({
    name: tool.name,
    description: tool.description ?? "",
    input_schema: tool.inputSchema ?? { type: "object", properties: {} },
  }));
}

interface AnthropicContentBlock {
  type: string;
  text?: string;
  id?: string;
  name?: string;
  input?: unknown;
  tool_use_id?: string;
  content?: unknown;
  is_error?: boolean;
}

async function callAnthropic(
  apiKey: string,
  model: string,
  system: string,
  tools: McpTool[],
  messages: unknown[],
): Promise<{ stop_reason: string; content: AnthropicContentBlock[] }> {
  const res = await fetch(ANTHROPIC_API_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": ANTHROPIC_VERSION,
    },
    body: JSON.stringify({
      model,
      max_tokens: MAX_TOKENS,
      system,
      tools: toAnthropicTools(tools),
      messages,
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Anthropic API error ${res.status}: ${body}`);
  }
  return res.json() as Promise<{ stop_reason: string; content: AnthropicContentBlock[] }>;
}

export async function runChat(options: {
  apiKey: string;
  model: string;
  tools: McpTool[];
  history: unknown[];
  message: string;
  context: ChatContext;
}): Promise<{ turns: ChatTurn[]; anthropicHistory: unknown[] }> {
  const { apiKey, model, tools, message, context } = options;
  const system = buildSystemPrompt(context);
  const messages: unknown[] = [...options.history, { role: "user", content: message }];
  const turns: ChatTurn[] = [];

  for (let round = 0; round < MAX_TOOL_ROUNDS; round += 1) {
    const response = await callAnthropic(apiKey, model, system, tools, messages);
    messages.push({ role: "assistant", content: response.content });

    const text = response.content
      .filter((block) => block.type === "text" && block.text)
      .map((block) => block.text)
      .join("\n");
    const toolUses = response.content.filter((block) => block.type === "tool_use");

    if (toolUses.length === 0) {
      turns.push({ role: "assistant", text });
      return { turns, anthropicHistory: messages };
    }

    const toolResultBlocks: AnthropicContentBlock[] = [];
    const toolCalls: ChatTurn["toolCalls"] = [];
    for (const use of toolUses) {
      const name = use.name ?? "unknown_tool";
      const input = (use.input ?? {}) as Record<string, unknown>;
      try {
        const result = await mcpCallTool(name, input);
        toolCalls.push({ name, input, result: result.content });
        toolResultBlocks.push({
          type: "tool_result",
          tool_use_id: use.id,
          content: JSON.stringify(result.content),
          is_error: result.isError,
        });
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        toolCalls.push({ name, input, error: errorMessage });
        toolResultBlocks.push({
          type: "tool_result",
          tool_use_id: use.id,
          content: errorMessage,
          is_error: true,
        });
      }
    }

    turns.push({ role: "assistant", text, toolCalls });
    messages.push({ role: "user", content: toolResultBlocks });
  }

  turns.push({
    role: "assistant",
    text: "Stopped after too many tool-call rounds without a final answer.",
  });
  return { turns, anthropicHistory: messages };
}

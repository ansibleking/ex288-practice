import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { McpCallResult, McpTool } from "./types.js";

let client: Client | null = null;
let connectedUrl: string | null = null;

export async function mcpConnect(url: string): Promise<{ ok: boolean; error?: string }> {
  await mcpDisconnect();
  try {
    const transport = new StreamableHTTPClientTransport(new URL(url));
    const next = new Client({ name: "redfish-mcp-client", version: "0.1.0" });
    await next.connect(transport);
    client = next;
    connectedUrl = url;
    return { ok: true };
  } catch (err) {
    client = null;
    connectedUrl = null;
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

export async function mcpDisconnect(): Promise<void> {
  if (client) {
    try {
      await client.close();
    } catch {
      // already closed / unreachable, nothing to do
    }
  }
  client = null;
  connectedUrl = null;
}

function requireClient(): Client {
  if (!client) {
    throw new Error("Not connected to an MCP server. Set the server URL in Settings first.");
  }
  return client;
}

export async function mcpListTools(): Promise<McpTool[]> {
  const { tools } = await requireClient().listTools();
  return tools as McpTool[];
}

export async function mcpCallTool(
  name: string,
  args: Record<string, unknown>,
): Promise<McpCallResult> {
  const result = await requireClient().callTool({ name, arguments: args });
  return { isError: Boolean(result.isError), content: result.content };
}

export function mcpCurrentUrl(): string | null {
  return connectedUrl;
}

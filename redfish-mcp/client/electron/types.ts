export interface McpTool {
  name: string;
  description?: string;
  inputSchema: {
    type?: string;
    properties?: Record<string, any>;
    required?: string[];
    [key: string]: any;
  };
}

export interface McpCallResult {
  isError: boolean;
  content: unknown;
}

export interface EndpointInfo {
  name: string;
  base_url: string;
  read_only: boolean;
  default: boolean;
}

export interface Settings {
  serverUrl: string;
  model: string;
  hasApiKey: boolean;
}

export interface SettingsInput {
  serverUrl?: string;
  model?: string;
  apiKey?: string | null;
}

export type ChatRole = "user" | "assistant";

export interface ChatToolCall {
  name: string;
  input: unknown;
  result?: unknown;
  error?: string;
}

export interface ChatTurn {
  role: ChatRole;
  text: string;
  toolCalls?: ChatToolCall[];
}

export interface ChatContext {
  activeEndpoint: string | null;
  endpoints: EndpointInfo[];
}

export interface ChatSendResult {
  turns: ChatTurn[];
  anthropicHistory: unknown[];
}

export interface RedfishApi {
  mcp: {
    connect(url: string): Promise<{ ok: boolean; error?: string }>;
    disconnect(): Promise<void>;
    listTools(): Promise<McpTool[]>;
    callTool(name: string, args: Record<string, unknown>): Promise<McpCallResult>;
  };
  settings: {
    get(): Promise<Settings>;
    set(input: SettingsInput): Promise<Settings>;
  };
  chat: {
    send(
      message: string,
      anthropicHistory: unknown[],
      context: ChatContext,
    ): Promise<ChatSendResult | { error: string }>;
  };
}

declare global {
  interface Window {
    api: RedfishApi;
  }
}

import { useEffect, useState } from "react";
import type { EndpointInfo, McpTool } from "../electron/types";
import { SettingsPanel } from "./components/SettingsPanel";
import { ToolExplorer } from "./components/ToolExplorer";
import { ChatPanel } from "./components/ChatPanel";

type Tab = "dashboard" | "chat" | "settings";
type ConnState = "idle" | "connecting" | "connected" | "error";

function parseEndpoints(content: unknown): EndpointInfo[] {
  if (!Array.isArray(content)) return [];
  const textBlock = content.find(
    (block): block is { type: string; text: string } =>
      typeof block === "object" && block !== null && (block as any).type === "text",
  );
  if (!textBlock) return [];
  try {
    const parsed = JSON.parse(textBlock.text);
    return Array.isArray(parsed.endpoints) ? parsed.endpoints : [];
  } catch {
    return [];
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [connState, setConnState] = useState<ConnState>("idle");
  const [connError, setConnError] = useState<string | null>(null);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [endpoints, setEndpoints] = useState<EndpointInfo[]>([]);
  const [activeEndpoint, setActiveEndpoint] = useState<string | null>(null);

  async function connect(url: string) {
    setConnState("connecting");
    setConnError(null);
    const res = await window.api.mcp.connect(url);
    if (res.ok) {
      setConnState("connected");
      try {
        setTools(await window.api.mcp.listTools());
      } catch {
        setTools([]);
      }
      try {
        const result = await window.api.mcp.callTool("list_endpoints", {});
        const list = parseEndpoints(result.content);
        setEndpoints(list);
        setActiveEndpoint(list.find((e) => e.default)?.name ?? list[0]?.name ?? null);
      } catch {
        setEndpoints([]);
        setActiveEndpoint(null);
      }
    } else {
      setConnState("error");
      setConnError(res.error ?? "Unknown connection error");
    }
  }

  useEffect(() => {
    window.api.settings.get().then((s) => connect(s.serverUrl));
  }, []);

  const statusClass =
    connState === "connected" ? "connected" : connState === "error" ? "error" : "";
  const statusText =
    connState === "connected"
      ? `Connected · ${tools.length} tools · ${endpoints.length} server${endpoints.length === 1 ? "" : "s"}`
      : connState === "connecting"
        ? "Connecting…"
        : connState === "error"
          ? connError ?? "Connection error"
          : "Not connected";

  return (
    <div className="app">
      <div className="topbar">
        <strong>Redfish MCP Client</strong>
        <div className="tabs">
          <button className={tab === "dashboard" ? "active" : ""} onClick={() => setTab("dashboard")}>
            Dashboard
          </button>
          <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>
            Chat
          </button>
          <button className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}>
            Settings
          </button>
        </div>

        {endpoints.length > 0 && (
          <div className="endpoint-picker">
            Server:
            <select value={activeEndpoint ?? ""} onChange={(e) => setActiveEndpoint(e.target.value)}>
              {endpoints.map((e) => (
                <option key={e.name} value={e.name}>
                  {e.name}
                  {e.read_only ? " (read-only)" : ""}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className={"status " + statusClass}>
          <span className="dot" />
          {statusText}
        </div>
      </div>

      <div className="content">
        {tab === "dashboard" && (
          <ToolExplorer tools={tools} connected={connState === "connected"} activeEndpoint={activeEndpoint} />
        )}
        {tab === "chat" && (
          <ChatPanel
            connected={connState === "connected"}
            activeEndpoint={activeEndpoint}
            endpoints={endpoints}
          />
        )}
        {tab === "settings" && <SettingsPanel onReconnect={connect} />}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import type { Settings } from "../../electron/types";

export function SettingsPanel({ onReconnect }: { onReconnect: (url: string) => void }) {
  const [settings, setSettingsState] = useState<Settings | null>(null);
  const [serverUrl, setServerUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    window.api.settings.get().then((s) => {
      setSettingsState(s);
      setServerUrl(s.serverUrl);
      setModel(s.model);
    });
  }, []);

  async function handleSave() {
    const updated = await window.api.settings.set({
      serverUrl,
      model,
      ...(apiKey ? { apiKey } : {}),
    });
    setSettingsState(updated);
    setApiKey("");
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    onReconnect(serverUrl);
  }

  if (!settings) return <div className="panel">Loading…</div>;

  return (
    <div className="panel">
      <h2>Settings</h2>

      <div className="field">
        <label>MCP server URL (streamable-http endpoint)</label>
        <input
          value={serverUrl}
          onChange={(e) => setServerUrl(e.target.value)}
          placeholder="http://127.0.0.1:8787/mcp"
        />
        <span className="hint">
          Matches the port published in docker-compose.yml for the redfish-mcp container. One
          server here fronts your whole fleet — see endpoints.json on the server side.
        </span>
      </div>

      <div className="field">
        <label>Chat model</label>
        <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="claude-sonnet-5" />
      </div>

      <div className="field">
        <label>Anthropic API key {settings.hasApiKey ? "(set — leave blank to keep)" : "(not set)"}</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-ant-..."
        />
        <span className="hint">
          Stored locally, encrypted with your OS keychain via Electron's safeStorage. Only needed
          for the Chat tab — the Dashboard tab calls tools directly without an LLM.
        </span>
      </div>

      <div className="row">
        <button onClick={handleSave}>Save</button>
        {saved && <span className="hint" style={{ color: "var(--ok)" }}>Saved</span>}
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import type { McpTool } from "../../electron/types";
import { buildDefaultArgs, isSimpleType, type JsonSchemaProperty } from "../lib/schemaForm";

export function ToolExplorer({
  tools,
  connected,
  activeEndpoint,
}: {
  tools: McpTool[];
  connected: boolean;
  activeEndpoint: string | null;
}) {
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [args, setArgs] = useState<Record<string, unknown>>({});
  const [jsonArgs, setJsonArgs] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ isError: boolean; content: unknown } | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return tools;
    return tools.filter(
      (t) => t.name.toLowerCase().includes(q) || (t.description ?? "").toLowerCase().includes(q),
    );
  }, [tools, filter]);

  const activeTool = tools.find((t) => t.name === selected) ?? null;
  const properties: Record<string, JsonSchemaProperty> = activeTool?.inputSchema?.properties ?? {};
  const required: string[] = activeTool?.inputSchema?.required ?? [];

  function selectTool(tool: McpTool) {
    setSelected(tool.name);
    setResult(null);
    setRunError(null);
    const overrides: Record<string, unknown> =
      "endpoint" in (tool.inputSchema?.properties ?? {}) && activeEndpoint
        ? { endpoint: activeEndpoint }
        : {};
    setArgs(buildDefaultArgs(tool.inputSchema?.properties, overrides));
    const json: Record<string, string> = {};
    for (const [key, prop] of Object.entries(tool.inputSchema?.properties ?? {})) {
      if (!isSimpleType(prop) && !(prop.enum && prop.enum.length > 0)) {
        json[key] = JSON.stringify(prop.default ?? (prop.type === "array" ? [] : {}), null, 2);
      }
    }
    setJsonArgs(json);
  }

  // Follow the fleet-wide endpoint picker: if the currently selected tool
  // takes an "endpoint" argument, keep it in sync with the global choice.
  useEffect(() => {
    if (activeTool && "endpoint" in properties && activeEndpoint) {
      setArgs((a) => ({ ...a, endpoint: activeEndpoint }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeEndpoint]);

  async function run() {
    if (!activeTool) return;
    setRunning(true);
    setRunError(null);
    setResult(null);
    try {
      const finalArgs: Record<string, unknown> = { ...args };
      for (const [key, raw] of Object.entries(jsonArgs)) {
        if (raw.trim() === "") continue;
        finalArgs[key] = JSON.parse(raw);
      }
      // Drop empty-string optional fields so we don't send "" for untouched inputs.
      for (const key of Object.keys(finalArgs)) {
        if (finalArgs[key] === "" && !required.includes(key)) delete finalArgs[key];
      }
      const res = await window.api.mcp.callTool(activeTool.name, finalArgs);
      setResult(res);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="explorer">
      <div className="tool-list">
        <div style={{ padding: 8 }}>
          <input
            style={{ width: "100%" }}
            placeholder="Filter tools…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        {!connected && <div className="hint" style={{ padding: "0 14px" }}>Not connected.</div>}
        {filtered.map((tool) => (
          <div
            key={tool.name}
            className={"tool-list-item" + (tool.name === selected ? " selected" : "")}
            onClick={() => selectTool(tool)}
          >
            <div>{tool.name}</div>
            {tool.description && <div className="desc">{tool.description.slice(0, 90)}</div>}
          </div>
        ))}
      </div>

      <div className="tool-detail">
        {!activeTool && <div className="hint">Select a tool on the left to run it.</div>}
        {activeTool && (
          <div>
            <h3>{activeTool.name}</h3>
            <p className="hint">{activeTool.description}</p>

            {Object.entries(properties).map(([key, prop]) => {
              const isRequired = required.includes(key);
              if (prop.enum && prop.enum.length > 0) {
                return (
                  <div className="field" key={key}>
                    <label>
                      {key}
                      {isRequired ? " *" : ""}
                    </label>
                    <select
                      value={String(args[key] ?? "")}
                      onChange={(e) => setArgs((a) => ({ ...a, [key]: e.target.value }))}
                    >
                      {prop.enum.map((opt) => (
                        <option key={String(opt)} value={String(opt)}>
                          {String(opt)}
                        </option>
                      ))}
                    </select>
                  </div>
                );
              }
              if (isSimpleType(prop)) {
                const type = Array.isArray(prop.type) ? prop.type[0] : prop.type;
                if (type === "boolean") {
                  return (
                    <div className="field" key={key}>
                      <label>
                        <input
                          type="checkbox"
                          checked={Boolean(args[key])}
                          onChange={(e) => setArgs((a) => ({ ...a, [key]: e.target.checked }))}
                        />{" "}
                        {key}
                        {isRequired ? " *" : ""}
                      </label>
                      {prop.description && <span className="hint">{prop.description}</span>}
                    </div>
                  );
                }
                return (
                  <div className="field" key={key}>
                    <label>
                      {key}
                      {isRequired ? " *" : ""}
                      {key === "endpoint" ? " (fleet server — follows the picker above)" : ""}
                    </label>
                    <input
                      type={type === "number" || type === "integer" ? "number" : "text"}
                      value={String(args[key] ?? "")}
                      onChange={(e) =>
                        setArgs((a) => ({
                          ...a,
                          [key]:
                            type === "number" || type === "integer"
                              ? Number(e.target.value)
                              : e.target.value,
                        }))
                      }
                    />
                    {prop.description && <span className="hint">{prop.description}</span>}
                  </div>
                );
              }
              return (
                <div className="field" key={key} style={{ maxWidth: 640 }}>
                  <label>
                    {key} (JSON){isRequired ? " *" : ""}
                  </label>
                  <textarea
                    rows={4}
                    value={jsonArgs[key] ?? ""}
                    onChange={(e) => setJsonArgs((j) => ({ ...j, [key]: e.target.value }))}
                  />
                  {prop.description && <span className="hint">{prop.description}</span>}
                </div>
              );
            })}

            <button onClick={run} disabled={running || !connected}>
              {running ? "Running…" : "Run"}
            </button>

            {runError && <div className="error-banner">{runError}</div>}

            {result && (
              <div className={"result-box" + (result.isError ? " error-banner" : "")}>
                <pre>{JSON.stringify(result.content, null, 2)}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

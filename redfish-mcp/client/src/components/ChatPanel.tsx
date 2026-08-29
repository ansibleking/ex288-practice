import { useState } from "react";
import type { ChatTurn, EndpointInfo } from "../../electron/types";

export function ChatPanel({
  connected,
  activeEndpoint,
  endpoints,
}: {
  connected: boolean;
  activeEndpoint: string | null;
  endpoints: EndpointInfo[];
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [history, setHistory] = useState<unknown[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    const message = input.trim();
    if (!message || sending) return;
    setInput("");
    setError(null);
    setTurns((t) => [...t, { role: "user", text: message }]);
    setSending(true);
    try {
      const res = await window.api.chat.send(message, history, { activeEndpoint, endpoints });
      if ("error" in res) {
        setError(res.error);
      } else {
        setTurns((t) => [...t, ...res.turns]);
        setHistory(res.anthropicHistory);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="chat">
      <div className="chat-messages">
        {turns.length === 0 && (
          <div className="hint">
            Ask about your fleet in plain language — e.g. "what's the health of all servers?" or
            "list firmware on {activeEndpoint ?? "the default endpoint"}". Claude will call the
            relevant tool once per server when you ask about "all servers". Mutating actions still
            go through the server's write-mode gate.
          </div>
        )}
        {turns.map((turn, i) => (
          <div key={i} className={"chat-message " + turn.role}>
            {turn.text}
            {turn.toolCalls && turn.toolCalls.length > 0 && (
              <div className="tool-call-log">
                {turn.toolCalls.map((call, j) => (
                  <div key={j}>
                    → {call.name}({JSON.stringify(call.input)})
                    {call.error ? ` — error: ${call.error}` : ""}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {sending && <div className="chat-message assistant hint">Thinking…</div>}
      </div>

      {error && <div className="error-banner" style={{ margin: "0 16px" }}>{error}</div>}

      <div className="chat-input">
        <textarea
          value={input}
          placeholder={connected ? "Message…" : "Not connected to an MCP server"}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          onChange={(e) => setInput(e.target.value)}
        />
        <button onClick={send} disabled={sending}>
          Send
        </button>
      </div>
    </div>
  );
}

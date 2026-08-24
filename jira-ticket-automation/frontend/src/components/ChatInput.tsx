import { useRef, useState } from "react";

interface Props {
  text: string;
  onTextChange: (text: string) => void;
  onSubmitText: (text: string) => Promise<void>;
  onSubmitFile: (file: File) => Promise<void>;
}

export function ChatInput({ text, onTextChange, onSubmitText, onSubmitFile }: Props) {
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await onSubmitText(trimmed);
      onTextChange("");
    } finally {
      setBusy(false);
    }
  }

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || busy) return;
    setBusy(true);
    try {
      await onSubmitFile(file);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat-input-row">
      <textarea
        rows={3}
        value={text}
        placeholder="Describe what you're seeing (e.g. &quot;payments-svc is throwing intermittent 503s since 10:14 UTC&quot;)"
        onChange={(e) => onTextChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void handleSend();
          }
        }}
      />
      <div className="chat-input-actions">
        <button className="primary-button" onClick={() => void handleSend()} disabled={busy || !text.trim()}>
          {busy ? "Sending…" : "Send"}
        </button>
        <button onClick={() => fileInputRef.current?.click()} disabled={busy}>
          Upload .txt/.log
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.log,text/plain"
          style={{ display: "none" }}
          onChange={(e) => void handleFileChange(e)}
        />
      </div>
    </div>
  );
}

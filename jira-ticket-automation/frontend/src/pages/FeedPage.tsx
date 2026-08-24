import { useState } from "react";
import { FeedWizard } from "../components/FeedWizard";
import { ManagedTicketsPanel } from "../components/ManagedTicketsPanel";
import { outcomeText } from "../lib/explainRouting";
import type { FeedResponse } from "../types";

interface FeedEntry {
  id: string;
  inputText: string;
  response: FeedResponse;
}

let nextId = 0;
function newId(): string {
  nextId += 1;
  return `f${nextId}`;
}

export function FeedPage() {
  const [entries, setEntries] = useState<FeedEntry[]>([]);

  function handleSettled(inputText: string, response: FeedResponse) {
    setEntries((prev) => [{ id: newId(), inputText, response }, ...prev]);
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Feed</h1>
        <p>Describe a situation and let the AI classify, then create, update, or resolve the ticket.</p>
      </header>
      <div className="feed-page">
        <div className="feed-main">
          <FeedWizard onSettled={handleSettled} />

          {entries.length > 0 && (
            <div className="feed-log">
              <h2 className="feed-log-heading">Recent submissions (this session)</h2>
              {entries.map((entry) => (
                <div key={entry.id} className="feed-entry">
                  <p className="feed-entry-input">{entry.inputText}</p>
                  <p className="feed-entry-outcome">
                    <strong>{entry.response.classification.title}</strong> — {outcomeText(entry.response)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
        <ManagedTicketsPanel />
      </div>
    </div>
  );
}

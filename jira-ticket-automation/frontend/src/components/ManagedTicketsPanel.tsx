import { useEffect, useState } from "react";
import { listManagedTickets } from "../api";
import type { CandidateTicket } from "../types";
import { TicketDetailModal } from "./TicketDetailModal";

export function ManagedTicketsPanel() {
  const [tickets, setTickets] = useState<CandidateTicket[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);

  async function refresh() {
    setError(null);
    try {
      setTickets(await listManagedTickets());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load managed tickets");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="card sidebar-card">
      <div className="panel-header">
        <h2>Currently tracked</h2>
        <button onClick={() => void refresh()}>Refresh</button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {tickets === null && !error && <p className="empty-state">Loading…</p>}
      {tickets && tickets.length === 0 && <p className="empty-state">No open AI-managed tickets.</p>}
      {tickets && tickets.length > 0 && (
        <ul className="managed-tickets-list">
          {tickets.map((t) => (
            <li key={t.key}>
              <button className="link-button" onClick={() => setOpenKey(t.key)}>
                {t.key}
              </button>{" "}
              — {t.summary}
            </li>
          ))}
        </ul>
      )}
      {openKey && <TicketDetailModal ticketKey={openKey} onClose={() => setOpenKey(null)} />}
    </div>
  );
}

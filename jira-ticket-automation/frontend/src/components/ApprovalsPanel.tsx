import { useEffect, useState } from "react";
import { listApprovals } from "../api";
import type { ApprovalTicket } from "../types";
import { ApprovalDetailModal } from "./ApprovalDetailModal";

export function ApprovalsPanel() {
  const [tickets, setTickets] = useState<ApprovalTicket[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);

  async function refresh() {
    setError(null);
    try {
      setTickets(await listApprovals());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load approvals");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="card">
      <div className="panel-header">
        <h2>Pending your approval</h2>
        <button onClick={() => void refresh()}>Refresh</button>
      </div>
      <p className="panel-subtitle">
        Tickets assigned to you that are currently waiting on an approve/reject decision.
      </p>

      {error && <p className="error-text">{error}</p>}
      {tickets === null && !error && <p className="empty-state">Loading…</p>}
      {tickets && tickets.length === 0 && <p className="empty-state">Nothing waiting on your approval right now.</p>}
      {tickets && tickets.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Summary</th>
                <th>Type</th>
                <th>Status</th>
                <th>Reporter</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => (
                <tr key={t.key}>
                  <td>
                    <button className="link-button" onClick={() => setOpenKey(t.key)}>
                      {t.key}
                    </button>
                  </td>
                  <td className="input-cell">{t.summary}</td>
                  <td>{t.issue_type}</td>
                  <td>{t.status}</td>
                  <td>{t.reporter ?? "—"}</td>
                  <td className="num">{new Date(t.updated).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {openKey && (
        <ApprovalDetailModal
          ticketKey={openKey}
          onClose={() => setOpenKey(null)}
          onTransitioned={() => void refresh()}
        />
      )}
    </div>
  );
}

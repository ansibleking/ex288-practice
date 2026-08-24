import { useEffect, useState } from "react";
import { listMyTickets } from "../api";
import type { JiraTicketSummary } from "../types";
import { TicketDetailModal } from "./TicketDetailModal";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

export function MyTicketsPanel() {
  const [tickets, setTickets] = useState<JiraTicketSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);

  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [pageSize, setPageSize] = useState(20);
  const [offset, setOffset] = useState(0);

  async function refresh() {
    setError(null);
    try {
      const result = await listMyTickets({
        startDate: startDate || undefined,
        endDate: endDate || undefined,
        limit: pageSize,
        offset,
      });
      setTickets(result.items);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load your tickets");
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startDate, endDate, pageSize, offset]);

  function updateFilter(setter: (v: string) => void, value: string) {
    setter(value);
    setOffset(0);
  }

  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + pageSize, total);
  const canPrev = offset > 0;
  const canNext = offset + pageSize < total;

  return (
    <div className="card">
      <div className="panel-header">
        <h2>My tickets</h2>
        <button onClick={() => void refresh()}>Refresh</button>
      </div>
      <p className="panel-subtitle">Assigned to you or reported by you, from your Jira account.</p>

      <div className="ticket-filters">
        <label>
          From
          <input type="date" value={startDate} onChange={(e) => updateFilter(setStartDate, e.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={endDate} onChange={(e) => updateFilter(setEndDate, e.target.value)} />
        </label>
        <label>
          Per page
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setOffset(0);
            }}
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="error-text">{error}</p>}
      {tickets === null && !error && <p className="empty-state">Loading…</p>}
      {tickets && tickets.length === 0 && <p className="empty-state">No tickets assigned to or reported by you.</p>}
      {tickets && tickets.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Summary</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th>Type</th>
                  <th>Assignee</th>
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
                    <td>{t.status}</td>
                    <td>{t.priority ?? "—"}</td>
                    <td>{t.issue_type}</td>
                    <td>{t.assignee ?? "Unassigned"}</td>
                    <td className="num">{new Date(t.updated).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination-row">
            <span className="pagination-summary">
              {rangeStart}–{rangeEnd} of {total}
            </span>
            <div className="pagination-controls">
              <button disabled={!canPrev} onClick={() => setOffset((o) => Math.max(0, o - pageSize))}>
                ← Prev
              </button>
              <button disabled={!canNext} onClick={() => setOffset((o) => o + pageSize)}>
                Next →
              </button>
            </div>
          </div>
        </>
      )}
      {openKey && <TicketDetailModal ticketKey={openKey} onClose={() => setOpenKey(null)} />}
    </div>
  );
}

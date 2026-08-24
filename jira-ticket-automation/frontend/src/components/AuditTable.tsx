import { Fragment, useEffect, useState } from "react";
import { listAudit } from "../api";
import type { ActionStatus, AuditRow } from "../types";

const STATUS_OPTIONS: (ActionStatus | "")[] = [
  "",
  "executed",
  "pending_confirmation",
  "confirmed",
  "cancelled",
  "skipped",
  "failed",
];

function statusMessage(row: AuditRow): string {
  if (row.jira_error) return row.jira_error;
  switch (row.action_status) {
    case "executed":
      return row.jira_issue_key
        ? `Executed automatically — ${row.jira_issue_key} created/updated in Jira.`
        : "Executed automatically.";
    case "confirmed":
      return row.jira_issue_key
        ? `Confirmed by you and executed — ${row.jira_issue_key}.`
        : "Confirmed by you and executed.";
    case "pending_confirmation":
      return "Waiting for you to confirm — nothing has touched Jira yet.";
    case "skipped":
      return "Classified as noise — not actionable, no Jira action taken.";
    case "cancelled":
      return "Cancelled by you — no Jira action was taken.";
    default:
      return row.action_status;
  }
}

export function AuditTable() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [status, setStatus] = useState<ActionStatus | "">("");
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  async function refresh() {
    setError(null);
    try {
      setRows(await listAudit(50, 0, status || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit history");
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  return (
    <div className="card">
      <div className="panel-header">
        <h2>Audit history</h2>
        <div className="audit-controls">
          <select value={status} onChange={(e) => setStatus(e.target.value as ActionStatus | "")}>
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt || "all statuses"}
              </option>
            ))}
          </select>
          <button onClick={() => void refresh()}>Refresh</button>
        </div>
      </div>
      <p className="panel-subtitle">Click a row's status to show its full message — you can select and copy it.</p>
      {error && <p className="error-text">{error}</p>}
      {rows && rows.length === 0 && <p className="empty-state">No audit entries yet.</p>}
      {rows && rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Input</th>
                <th>Intent</th>
                <th>Severity</th>
                <th>Confidence</th>
                <th>Decision</th>
                <th>Status</th>
                <th>Jira</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isOpen = expandedId === row.id;
                return (
                  <Fragment key={row.id}>
                    <tr className={`stripe-${row.llm_severity}`}>
                      <td className="num">{new Date(row.created_at).toLocaleString()}</td>
                      <td className="input-cell" title={row.input_text}>
                        {row.input_text.length > 80 ? `${row.input_text.slice(0, 80)}…` : row.input_text}
                      </td>
                      <td>{row.llm_intent}</td>
                      <td>{row.llm_severity}</td>
                      <td className="num">{Math.round(row.llm_confidence * 100)}%</td>
                      <td>{row.routing_decision}</td>
                      <td>
                        <button
                          type="button"
                          className={`status-pill status-${row.action_status} status-pill-toggle`}
                          onClick={() => setExpandedId(isOpen ? null : row.id)}
                          aria-expanded={isOpen}
                        >
                          {row.action_status}
                          {row.jira_error && " ⚠"}
                        </button>
                      </td>
                      <td className="input-cell mono">{row.jira_issue_key ?? "—"}</td>
                    </tr>
                    {isOpen && (
                      <tr className="detail-row">
                        <td colSpan={8}>
                          <p className="detail-message">{statusMessage(row)}</p>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

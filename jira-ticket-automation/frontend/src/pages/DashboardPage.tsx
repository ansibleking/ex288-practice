import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listAudit, listManagedTickets, listPending, listSchedule } from "../api";
import { dayRangeIso, todayLocalDate } from "../lib/scheduleTime";
import type { AuditRow, CandidateTicket, ScheduledItem } from "../types";

function StatCard({ label, value, to }: { label: string; value: string | number; to: string }) {
  return (
    <Link to={to} className="stat-card">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </Link>
  );
}

export function DashboardPage() {
  const [managed, setManaged] = useState<CandidateTicket[] | null>(null);
  const [pending, setPending] = useState<AuditRow[] | null>(null);
  const [today, setToday] = useState<ScheduledItem[] | null>(null);
  const [recent, setRecent] = useState<AuditRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const date = todayLocalDate();
    const { start, end } = dayRangeIso(date);
    Promise.all([listManagedTickets(), listPending(), listSchedule(start, end), listAudit(8)])
      .then(([m, p, s, a]) => {
        setManaged(m);
        setPending(p);
        setToday(s);
        setRecent(a);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load dashboard"));
  }, []);

  const upcoming = today?.filter((i) => i.status === "pending" || i.status === "created") ?? null;

  return (
    <div className="page">
      <header className="page-header">
        <h1>Dashboard</h1>
        <p>An at-a-glance view of what's tracked, pending, scheduled, and recently decided.</p>
      </header>

      {error && <p className="error-text">{error}</p>}

      <div className="stat-grid">
        <StatCard label="Currently tracked tickets" value={managed?.length ?? "—"} to="/feed" />
        <StatCard label="Awaiting your confirmation" value={pending?.length ?? "—"} to="/audit" />
        <StatCard label="Scheduled today" value={today?.length ?? "—"} to="/scheduler" />
      </div>

      <div className="dashboard-grid">
        <div className="card">
          <div className="panel-header">
            <h2>Needs your confirmation</h2>
            <Link to="/audit">View all</Link>
          </div>
          {pending === null && <p className="empty-state">Loading…</p>}
          {pending && pending.length === 0 && <p className="empty-state">Nothing waiting on you.</p>}
          {pending && pending.length > 0 && (
            <ul className="dashboard-list">
              {pending.slice(0, 6).map((row) => (
                <li key={row.id}>
                  <strong>{row.llm_title}</strong>
                  <span className="dashboard-list-meta">
                    {row.llm_intent} · {row.llm_severity} · {Math.round(row.llm_confidence * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <div className="panel-header">
            <h2>Today's schedule</h2>
            <Link to="/scheduler">Open scheduler</Link>
          </div>
          {upcoming === null && <p className="empty-state">Loading…</p>}
          {upcoming && upcoming.length === 0 && <p className="empty-state">Nothing scheduled for today.</p>}
          {upcoming && upcoming.length > 0 && (
            <ul className="dashboard-list">
              {upcoming.slice(0, 6).map((item) => (
                <li key={item.id}>
                  <strong>
                    {new Date(item.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </strong>{" "}
                  {item.text.length > 60 ? `${item.text.slice(0, 60)}…` : item.text}
                  <span className={`status-pill status-schedule-${item.status}`}>{item.status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card dashboard-recent">
          <div className="panel-header">
            <h2>Recent activity</h2>
            <Link to="/audit">Full history</Link>
          </div>
          {recent === null && <p className="empty-state">Loading…</p>}
          {recent && recent.length === 0 && <p className="empty-state">No activity yet.</p>}
          {recent && recent.length > 0 && (
            <ul className="dashboard-list">
              {recent.map((row) => (
                <li key={row.id}>
                  <strong>{row.llm_title}</strong>
                  <span className={`status-pill status-${row.action_status}`}>{row.action_status}</span>
                  <span className="dashboard-list-meta">{new Date(row.created_at).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

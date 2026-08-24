import { AuditTable } from "../components/AuditTable";

export function AuditPage() {
  return (
    <div className="page">
      <header className="page-header">
        <h1>Audit History</h1>
        <p>Every AI decision — created, updated, resolved, skipped, or proposed — independent of Jira.</p>
      </header>
      <AuditTable />
    </div>
  );
}
